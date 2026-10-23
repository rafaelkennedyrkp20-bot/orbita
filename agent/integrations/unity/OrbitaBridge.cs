// Órbita Unity bridge — OrbitaUnity/1. Somente Editor; não entra no jogo compilado.
// Instalada com permissão em Assets/Editor. Remova o arquivo para desligar a ponte.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Orbita.EditorBridge
{
    [InitializeOnLoad]
    internal static class OrbitaBridge
    {
        private const int Port = 30012;
        private const string Protocol = "OrbitaUnity/1";
        private static readonly ConcurrentQueue<Job> Pending = new ConcurrentQueue<Job>();
        private static TcpListener listener;
        private static Thread worker;
        private static volatile bool stopping;
        private static string token;

        private sealed class Job
        {
            internal string Method, Path, Body, Response;
            internal int Status = 200, State;
            internal readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
        }
        [Serializable] private sealed class PrimitiveRequest
        {
            public string primitive = "", name = "";
            public Vector3 position = new Vector3();
        }
        [Serializable] private sealed class ErrorResponse { public string error; }
        [Serializable] private sealed class ObjectData
        {
            public string name;
            public int instance_id, parent_id;
            public Vector3 position, rotation, scale;
            public bool active;
        }
        [Serializable] private sealed class SceneResponse
        {
            public string protocol = Protocol, scene;
            public bool truncated;
            public List<ObjectData> objects = new List<ObjectData>();
        }
        [Serializable] private sealed class CreatedResponse
        {
            public string protocol = Protocol;
            public ObjectData created;
        }

        static OrbitaBridge()
        {
            EditorApplication.update += Dispatch;
            AssemblyReloadEvents.beforeAssemblyReload += Stop;
            EditorApplication.quitting += Stop;
            // Nenhuma API de cena é usada antes do import terminar.
            EditorApplication.delayCall += Start;
        }

        private static void Start()
        {
            if (listener != null || stopping) return;
            try
            {
                string root = Directory.GetParent(Application.dataPath).FullName;
                string path = Path.Combine(root, "Library", "Orbita", "bridge-token.txt");
                if (!File.Exists(path)) throw new InvalidOperationException("Token ausente; reinstale a ponte pelo Órbita.");
                token = File.ReadAllText(path).Trim();
                if (token.Length != 64) throw new InvalidOperationException("Token local inválido.");
                listener = new TcpListener(IPAddress.Loopback, Port);
                listener.Start(8);
                worker = new Thread(Listen) { IsBackground = true, Name = "Orbita Unity HTTP" };
                worker.Start();
                Debug.Log("Órbita: ponte Unity local ativa em 127.0.0.1:" + Port + ".");
            }
            catch (Exception error)
            {
                if (listener != null) listener.Stop();
                listener = null;
                Debug.LogWarning("Órbita: ponte Unity indisponível (outro projeto pode ocupar a porta). " + error.Message);
            }
        }

        private static void Listen()
        {
            while (!stopping)
            {
                TcpClient client;
                try { client = listener.AcceptTcpClient(); }
                catch (SocketException) { break; }
                catch (ObjectDisposedException) { break; }
                using (client)
                {
                    client.ReceiveTimeout = client.SendTimeout = 5000;
                    try { Handle(client.GetStream()); }
                    catch (IOException) { }
                    catch (SocketException) { }
                    catch (Exception) { /* Pedido inválido: fecha só esta conexão. */ }
                }
            }
        }

        private static string ReadLine(NetworkStream stream, ref int used)
        {
            var data = new List<byte>();
            while (true)
            {
                int value = stream.ReadByte();
                if (value < 0) throw new IOException("Cabeçalho incompleto.");
                if (++used > 16384) throw new IOException("Cabeçalho grande demais.");
                if (value == 10) break;
                if (value != 13) data.Add((byte)value);
            }
            return Encoding.ASCII.GetString(data.ToArray());
        }

        private static void Handle(NetworkStream stream)
        {
            int used = 0;
            string[] request = ReadLine(stream, ref used).Split(' ');
            if (request.Length != 3 || request[2] != "HTTP/1.1") { Reply(stream, 400, "{}"); return; }
            var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            string line;
            while ((line = ReadLine(stream, ref used)).Length != 0)
            {
                int colon = line.IndexOf(':');
                if (colon < 1 || headers.ContainsKey(line.Substring(0, colon))) { Reply(stream, 400, "{}"); return; }
                headers.Add(line.Substring(0, colon), line.Substring(colon + 1).Trim());
            }
            string supplied, host;
            if (headers.ContainsKey("Origin") || headers.ContainsKey("Transfer-Encoding") ||
                !headers.TryGetValue("Host", out host) || host != "127.0.0.1:" + Port ||
                !headers.TryGetValue("X-Orbita-Token", out supplied) || supplied != token)
            { Reply(stream, 403, "{}"); return; }
            int length = 0;
            string lengthHeader;
            if (headers.TryGetValue("Content-Length", out lengthHeader) &&
                (!int.TryParse(lengthHeader, out length) || length < 0 || length > 65536))
            { Reply(stream, 413, "{}"); return; }
            var body = new byte[length];
            for (int offset = 0; offset < length;)
            {
                int read = stream.Read(body, offset, length - offset);
                if (read == 0) throw new IOException("Corpo incompleto.");
                offset += read;
            }
            if (request[0] == "GET" && request[1] == "/orbita/info")
            {
                Reply(stream, 200, "{\"protocol\":\"OrbitaUnity/1\",\"scene_limit\":1000,\"arbitrary_code\":false}");
                return;
            }
            if (!((request[0] == "GET" && request[1] == "/orbita/scene") ||
                  (request[0] == "POST" && request[1] == "/orbita/primitive" && length > 0)))
            { Reply(stream, 404, "{}"); return; }
            var job = new Job { Method = request[0], Path = request[1], Body = Encoding.UTF8.GetString(body) };
            Pending.Enqueue(job);
            if (!job.Done.Wait(8000))
            {
                // Se ainda estava na fila, o editor não deve executar depois do timeout.
                Interlocked.CompareExchange(ref job.State, 2, 0);
                Reply(stream, 504, "{\"error\":\"Editor ocupado; confira a cena antes de repetir.\"}");
                return;
            }
            Reply(stream, job.Status, job.Response);
        }

        private static void Dispatch()
        {
            if (stopping || EditorApplication.isCompiling || EditorApplication.isUpdating) return;
            Job job;
            if (!Pending.TryDequeue(out job) || Interlocked.CompareExchange(ref job.State, 1, 0) != 0) return;
            try
            {
                var scene = SceneManager.GetActiveScene();
                if (!scene.IsValid() || !scene.isLoaded) throw new InvalidOperationException("Abra uma cena no Editor.");
                if (job.Path == "/orbita/scene")
                {
                    var result = new SceneResponse { scene = scene.path };
                    var queue = new Queue<Transform>();
                    foreach (GameObject root in scene.GetRootGameObjects()) queue.Enqueue(root.transform);
                    while (queue.Count > 0 && result.objects.Count < 1000)
                    {
                        Transform current = queue.Dequeue();
                        result.objects.Add(Describe(current));
                        foreach (Transform child in current) queue.Enqueue(child);
                    }
                    result.truncated = queue.Count > 0;
                    job.Response = JsonUtility.ToJson(result);
                }
                else
                {
                    if (EditorApplication.isPlayingOrWillChangePlaymode)
                        throw new InvalidOperationException("Pare o Play Mode antes de editar pelo Órbita.");
                    PrimitiveRequest args = JsonUtility.FromJson<PrimitiveRequest>(job.Body);
                    PrimitiveType kind;
                    if (args == null || string.IsNullOrWhiteSpace(args.name) || args.name.Length > 120 ||
                        !Enum.TryParse(args.primitive, true, out kind) || !Enum.IsDefined(typeof(PrimitiveType), kind) ||
                        !Finite(args.position.x) || !Finite(args.position.y) || !Finite(args.position.z))
                        throw new ArgumentException("Nome, primitiva ou posição inválidos.");
                    GameObject created = GameObject.CreatePrimitive(kind);
                    Undo.RegisterCreatedObjectUndo(created, "Órbita: criar " + args.name);
                    created.name = args.name;
                    created.transform.position = args.position;
                    EditorSceneManager.MarkSceneDirty(scene);
                    job.Response = JsonUtility.ToJson(new CreatedResponse { created = Describe(created.transform) });
                }
            }
            catch (Exception error)
            {
                job.Status = 400;
                job.Response = JsonUtility.ToJson(new ErrorResponse { error = error.Message });
            }
            finally { Interlocked.Exchange(ref job.State, 3); job.Done.Set(); }
        }

        private static bool Finite(float value)
        { return !float.IsNaN(value) && !float.IsInfinity(value) && Mathf.Abs(value) <= 1000000; }

        private static ObjectData Describe(Transform value)
        {
            return new ObjectData { name = value.name, instance_id = value.gameObject.GetInstanceID(),
                parent_id = value.parent == null ? 0 : value.parent.gameObject.GetInstanceID(), active = value.gameObject.activeSelf,
                position = value.position, rotation = value.eulerAngles, scale = value.localScale };
        }

        private static void Reply(NetworkStream stream, int status, string content)
        {
            byte[] body = Encoding.UTF8.GetBytes(content ?? "{}");
            byte[] header = Encoding.ASCII.GetBytes("HTTP/1.1 " + status + " Orbita\r\nContent-Type: application/json; charset=utf-8\r\n" +
                "Content-Length: " + body.Length + "\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n");
            stream.Write(header, 0, header.Length);
            stream.Write(body, 0, body.Length);
        }

        private static void Stop()
        {
            stopping = true;
            if (listener != null) listener.Stop();
            Job job;
            while (Pending.TryDequeue(out job))
            {
                Interlocked.Exchange(ref job.State, 2);
                job.Status = 503;
                job.Response = "{\"error\":\"Editor recompilando ou fechando.\"}";
                job.Done.Set();
            }
        }
    }
}
