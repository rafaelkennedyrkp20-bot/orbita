# Estúdio 3D — uso e limites

Implementação de 23/10/2026, ainda sem alteração da versão pública. Abra **Conexões → Estúdio 3D**
no Órbita reiniciado. O painel separa configuração e diagnóstico das abas Programas, MCP e Skills.
Os pedidos de exemplo apenas preenchem o chat: você pode editar antes de enviar.

## O que está integrado

| Programa | Caminho nativo | O que a IA pode fazer |
|---|---|---|
| Blender | Python `bpy`, processo separado | Executar script do projeto, modelar, renderizar e exportar GLB/FBX/STL |
| Unreal Engine | API oficial Remote Control HTTP | Inspecionar um UObject conhecido e chamar funções Blueprint-callable |
| Unity | Ponte C# do Órbita em `Assets/Editor` | Consultar hierarquia da cena ativa e criar primitivas com Desfazer |
| Godot | CLI headless | Importar/validar projeto e executar scripts/cenas com argumentos nativos |
| OpenSCAD | CLI | Converter `.scad` em STL e gerar prévia PNG |
| Outros aplicativos | MCP existente | Ferramentas oferecidas pelo servidor compatível que a pessoa configurar |

Integração de ferramenta não é geração nativa de malha pela API do modelo. O modelo escreve scripts,
chama o programa e verifica arquivos/prévias. Não há promessa de suporte automático a todo aplicativo:
Maya, Houdini, 3ds Max e outros precisam de adaptador/servidor compatível e instalação própria.

## Fluxo simples pelo chat

1. Abra a pasta do projeto no Órbita e escolha o modelo/API.
2. Peça: **“Confira minhas ferramentas 3D e prepare o necessário para criar este objeto.”**
3. A IA usa `studio3d_status`; `refresh=true` consulta os protocolos locais, sem alterar a cena.
   Ela pode salvar o endereço local com `studio3d_configure`, sujeito à permissão de escrita, e testar em seguida.
   Assim a configuração não depende de editar um JSON ou preencher o painel manualmente.
4. Se faltar Blender, Godot ou OpenSCAD, a IA oferece `toolbox_install` com o ID do programa.
   A instalação segue as permissões normais e o catálogo existente: fonte oficial, versão fixa e SHA-256.
   Também pode instalar por **Programas**. Não há download silencioso ao abrir o estúdio.
5. Unity/Unreal são instalados pelos distribuidores oficiais; não estão no instalador portátil do Órbita.
6. Execute a tarefa com as ferramentas do programa e confira o resultado. Arquivo criado ou porta aberta
   não prova qualidade de cena/render: a IA deve abrir a prévia e verificar os arquivos exportados.

## Blender

Usa o executável da caixa de ferramentas ou do PATH. Para instalação fora desses locais, selecione
o executável no painel. Campo vazio mantém a detecção automática.

A IA salva um `.py` dentro do projeto e usa `blender_run_script(script_path, timeout)`.
O Blender roda em background, com início de fábrica e sem autoexec de arquivos carregados, usando a pasta
do projeto como diretório. O script explicitamente autorizado roda normalmente; isso não é um sandbox.
Erros Python resultam em saída não zero. Timeout entre 1 e 600 segundos; Parar encerra apenas a árvore
de processos iniciada por essa chamada. Saída é limitada e não ocupa contexto sem limite.

## Unreal Engine

1. No projeto aberto no Unreal, ative **Remote Control API** em Plugins e reinicie o editor.
2. No Output Log, execute `WebControl.StartServer`.
3. No estúdio, habilite Unreal e salve o endereço local; padrão `http://127.0.0.1:30010`.
4. Clique em **Testar conexões**. A resposta precisa anunciar a rota de chamada esperada em `/remote/info`.

`unreal_describe(object_path)` consulta propriedades e funções. `unreal_call(object_path, function_name,
parameters)` chama a função confirmada. Caminhos de objetos e nomes de parâmetros variam por projeto:
não se devem adivinhar. Chamadas usam `generateTransaction=true`, mas nem toda função é reversível.
Um timeout não prova que a operação falhou no editor; confira a cena antes de repetir.

## Unity

1. Abra a raiz de um projeto existente no Órbita: deve conter `Assets` e `ProjectSettings/ProjectVersion.txt`.
2. Peça **“Conecte este projeto Unity”** ou use o pedido pronto no estúdio.
3. Autorize `unity_install_bridge(project_path)`. Ela adiciona `Assets/Editor/OrbitaBridge.cs` e gera
   um token em `Library/Orbita/bridge-token.txt`; não sobrescreve uma ponte diferente já existente.
   A ferramenta é de risco `exec`: o Unity compila e executa scripts de editor quando importa o projeto.
4. Abra o mesmo projeto no Unity e aguarde a compilação. A conexão é local na porta 30012.
5. Use **Testar conexões**, ou peça `unity_scene` no chat.

O token fica no projeto, fora de Assets e da configuração pública do Órbita. A ponte só escuta em
loopback, exige autenticação e recusa requisições com Origin. Operações de cena são encaminhadas à thread
do editor. `unity_scene` limita a lista a 1.000 objetos; `unity_create_primitive` cria cubo, esfera, plano,
cápsula, cilindro ou quad e registra Desfazer. Não salva a cena, não altera durante Play Mode e não
oferece execução arbitrária de C# via HTTP. Modelos complexos podem ser criados no Blender e importados
pelo fluxo do projeto; importador e editor completo de assets Unity ainda não fazem parte da ponte.

Uma ponte ativa por porta. Se outro projeto ocupar 30012, confira o Console do Unity e feche a ponte
do projeto anterior. Remover `Assets/Editor/OrbitaBridge.cs` e aguardar recompilação desliga o serviço.

## Godot e OpenSCAD

`creative_app_run(app, arguments, timeout)` resolve o executável e passa uma lista de argumentos
diretamente ao programa, sem shell. O Godot recebe `--headless --path <projeto>` automaticamente.
Para OpenSCAD, use argumentos como `['-o', 'modelo.stl', 'modelo.scad']` e, para a prévia,
`['-o', 'previa.png', '--viewall', '--autocenter', 'modelo.scad']`.

São execuções reais, não validação de texto. Scripts/comandos podem gravar arquivos; permissões e políticas
se aplicam como no terminal. App ausente retorna instrução para pedir instalação, sem instalar sozinho.

## Modelos/API e equipe

As ferramentas usam o registro comum: não exigem uma marca de modelo. O perfil precisa liberar o grupo
`shell`; modelos sem tool-calling nativo continuam pelo mecanismo existente de ferramentas por prompt.

Moonshot/Kimi ganhou preset com `MOONSHOT_API_KEY` no `.env`, endpoint oficial e modelos K3.1 Pro/Highspeed.
A lista `/models` e o campo livre continuam disponíveis. Preservação obrigatória do raciocínio foi corrigida
para as gerações documentadas K3, K3.1 e K2.7 Code; o custo desse raciocínio entra no contexto.
Temperatura é omitida no preset e esforço K3/K3.1 aceita os valores documentados. Não foi feito ranking
de qualidade 3D nem chamada paga para avaliar o modelo.

A equipe pode dividir scripts, materiais e revisão. Unity/Unreal mantêm reserva por sessão até o fim do turno,
reaproveitando o controle de concorrência existente; não intercalam operações de dois agentes no mesmo editor.
Uma conexão reservada não pode ser redirecionada para outro projeto pela configuração. Escritas externas à
revisão de propostas e execuções que escapam ao destino controlado ficam bloqueadas nas políticas correspondentes.

## Evidência e próximos testes

- Base antes da mudança: **575 aprovados, 2 pulados**, em 155,51 s.
- Gate final: `venv\Scripts\python.exe -m pytest tests -q` — **661 aprovados, 2 pulados**, em **158,96 s**.
- `venv\Scripts\python.exe -m pyflakes agent tests launcher.py setup_voz.py`: zero avisos.
- `node --check agent/ui/web/app.js` e `git diff --check`: sem erros.
- Página real QtWebEngine conferida nos temas claro/escuro e largura reduzida; campos preservados em eventos MCP,
  HTML externo escapado, busca e abas testadas. Corrigido também o ciclo de vida de QApplication no novo teste,
  cuja destruição prematura impedia executar os testes gráficos antigos na mesma suíte.
- Blender **4.5.9 LTS real**, chamado por `blender_run_script`: saída 0, prévia PNG 640×480 (**299.562 bytes**),
  GLB (**17.060 bytes**, cabeçalho glTF 2 e tamanho verificados) e `.blend`. Render conferido visualmente.
- OpenSCAD **2021.01 real**, chamado por `creative_app_run`: saída 0, STL (**33.152 bytes**) e PNG de prévia
  (**6.200 bytes**), conferido visualmente. Não foi necessário baixar programas.
- Ponte C# compilada com `csc /warnaserror` contra stubs mínimos das APIs Unity: saída 0 e zero avisos.
  Isso verifica sintaxe e tipos básicos; **não substitui compilação no Unity real**.
- Revisão independente corrigiu troca indevida de destino enquanto editor estava reservado por uma sessão.
  Nova revisão não encontrou P0/P1 adicionais. `data/settings.json` manteve o SHA-256 original.

Testes de protocolo usam servidores HTTP locais controlados, e o transporte da API Kimi é simulado.
Testes de CLI incluem processos reais de teste. Unity/Unreal reais, compilação no Unity, Godot real e
chamadas pagas Kimi precisam de validação adicional; não são apresentados como comprovados por esses testes.
Os dois testes pulados são os testes existentes exclusivos de Linux/macOS em `test_portability.py`.

## Fontes oficiais consultadas em 23/10/2026

- [Epic: Remote Control Quick Start](https://dev.epicgames.com/documentation/en-us/unreal-engine/remote-control-quick-start-for-unreal-engine)
- [Epic: Remote Control HTTP reference](https://dev.epicgames.com/documentation/en-us/unreal-engine/remote-control-api-http-reference-for-unreal-engine)
- [Unity: EditorApplication.update](https://docs.unity3d.com/ScriptReference/EditorApplication-update.html)
- [Unity: Undo.RegisterCreatedObjectUndo](https://docs.unity3d.com/ScriptReference/Undo.RegisterCreatedObjectUndo.html)
- [Godot: linha de comando](https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html)
- [OpenSCAD: documentação](https://openscad.org/documentation.html)
- [Moonshot: Kimi K3.1 Pro](https://platform.kimi.ai/docs/guide/kimi-k3-1-pro-quickstart)
- [Moonshot: thinking models](https://platform.kimi.ai/docs/guide/use-thinking-models)
