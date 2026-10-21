"""DeepSeek pela conta do site, com login humano e navegador dedicado.

O site continua responsável pela autenticação e pelo protocolo de geração.
Observamos a resposta SSE para preservar Markdown e separar o raciocínio.
Objetos Playwright são criados e destruídos na thread que faz a chamada.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from agent.core.config import DATA_DIR
from agent.core.providers import ChatResult, Provider, ProviderError, ToolsUnsupported, _coordinated_inference

CHAT_URL = "https://chat.deepseek.com/"
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
MODELS = ["default", "expert", "default-thinking", "expert-thinking"]

# A cópia do fluxo não altera a resposta entregue ao site nem seus controles.
_OBSERVE_STREAM = r"""() => {
  if (window.__orbitaDeepSeek) return;
  const state = window.__orbitaDeepSeek = {lines: [], pending: '', done: false, error: '', started: false,
    createdSessionIds: new Set(), sessionId: null, headers: null};
  const original = window.fetch;
  state.originalFetch = original.bind(window);
  window.fetch = async function(input, init) {
    const url = typeof input === 'string' ? input : input.url;
    const parsed = url && new URL(url, location.href);
    if (parsed && parsed.origin === location.origin && parsed.pathname === '/api/v0/chat_session/create') {
      const response = await original.call(this, input, init);
      try {
        const payload = await response.clone().json();
        const id = payload.data?.biz_data?.chat_session?.id;
        if (response.ok && payload.code === 0 && typeof id === 'string') state.createdSessionIds.add(id);
      } catch (_) {}
      return response;
    }
    if (!parsed || parsed.origin !== location.origin || parsed.pathname !== '/api/v0/chat/completion')
      return original.call(this, input, init);
    if (init && typeof init.body === 'string') {
      try {
        const body = JSON.parse(init.body);
        body.model_type = state.model;
        body.thinking_enabled = state.thinking;
        body.search_enabled = state.search;
        state.sessionId = body.chat_session_id;
        state.headers = new Headers(init.headers);
        init = {...init, body: JSON.stringify(body)};
      } catch (_) { state.error = 'Formato de envio desconhecido'; state.done = true;
        throw new Error(state.error); }
    } else { state.error = 'Formato de envio desconhecido'; state.done = true;
      throw new Error(state.error); }
    state.started = true;
    let response;
    try { response = await original.call(this, input, init); }
    catch (error) { state.error = String(error); state.done = true; throw error; }
    if (!response.ok) { state.error = 'HTTP ' + response.status; state.done = true; return response; }
    (async () => {
      const reader = response.clone().body.getReader(), decoder = new TextDecoder();
      let size = 0;
      try {
        for (;;) {
          const part = await reader.read();
          if (part.done) break;
          const text = decoder.decode(part.value, {stream: true});
          size += text.length;
          if (size > 10000000) throw new Error('Resposta excedeu 10 MB');
          state.pending += text;
          const lines = state.pending.split('\n');
          state.pending = lines.pop();
          state.lines.push(...lines);
        }
        state.pending += decoder.decode();
        if (state.pending) state.lines.push(state.pending);
      } catch (error) { state.error = String(error); }
      finally { state.done = true; reader.releaseLock(); }
    })();
    return response;
  };
}"""
_DELETE_OWN_CHAT = """async () => {
  const s = window.__orbitaDeepSeek;
  if (!s || !s.started) return {ok: true, not_created: true};
  if (!s.sessionId || !s.createdSessionIds.has(s.sessionId))
    return {ok: false, error: 'A sessão não foi criada nesta chamada; exclusão recusada.'};
  const headers = new Headers(s.headers);
  headers.set('Content-Type', 'application/json');
  headers.delete('x-ds-pow-response');
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await s.originalFetch('/api/v0/chat_session/delete', {
      method: 'POST', headers, credentials: 'include', signal: controller.signal,
      body: JSON.stringify({chat_session_id: s.sessionId})});
    if (!response.ok) return {ok: false, error: 'HTTP ' + response.status};
    const payload = await response.json();
    if (payload.code !== 0) return {ok: false, error: String(payload.msg || 'Exclusão não confirmada pelo site')};
    s.createdSessionIds.delete(s.sessionId);
    return {ok: true};
  } catch (error) { return {ok: false, error: String(error)}; }
  finally { clearTimeout(timer); }
}"""
_DRAIN = """() => {
  const s = window.__orbitaDeepSeek;
  return {lines: s.lines.splice(0), done: s.done, error: s.error, started: s.started};
}"""


def profile_dir(cfg: dict | None = None) -> Path:
    return Path((cfg or {}).get("profile_dir") or os.getenv("ORBITA_DEEPSEEK_PROFILE_DIR")
                or DATA_DIR / "deepseek_web" / "profile").expanduser().resolve()


def _option(cfg: dict, key: str, environment: str) -> bool:
    value = cfg[key] if key in cfg else os.getenv(environment, "0")
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


def _cdp_url(cfg: dict) -> str:
    url = (cfg.get("cdp_url") or os.getenv("DEEPSEEK_CDP_URL") or "").strip()
    if url and urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProviderError("DeepSeek Web: o endereço CDP precisa apontar para este computador.")
    return url


def status(cfg: dict | None = None) -> dict:
    """Estado local, sem abrir navegador nem testar credenciais remotamente."""
    cfg = cfg or {}
    folder = profile_dir(cfg)
    return {"profile_dir": str(folder), "profile_exists": folder.is_dir(), "cdp_url": _cdp_url(cfg)}


def _session_lock(cfg: dict) -> threading.Lock:
    key = _cdp_url(cfg) or str(profile_dir(cfg))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _browser_page(cfg: dict, *, visible: bool = False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise ProviderError("DeepSeek Web precisa do Playwright: python -m pip install playwright; "
                            "depois python -m playwright install chromium.") from error
    context = page = None
    cdp = _cdp_url(cfg)
    try:
        with sync_playwright() as playwright:
            try:
                if cdp:
                    browser = playwright.chromium.connect_over_cdp(cdp, timeout=15000)
                    if not browser.contexts:
                        raise ProviderError("O Chrome conectado não tem um perfil aberto.")
                    context = browser.contexts[0]
                else:
                    options = {"headless": not visible}
                    if cfg.get("browser_channel"):
                        options["channel"] = cfg["browser_channel"]
                    context = playwright.chromium.launch_persistent_context(str(profile_dir(cfg)), **options)
                page = context.new_page()
                page.set_default_timeout(10000)
                page.add_init_script("(" + _OBSERVE_STREAM + ")()")
                page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=30000)
                yield page
            finally:
                # No CDP, fecha só a aba criada por nós. O navegador pertence à pessoa.
                if page is not None:
                    page.close()
                if context is not None and not cdp:
                    context.close()
    except ProviderError:
        raise
    except Exception as error:
        raise ProviderError("DeepSeek Web: não consegui usar o navegador. Confira o login com "
                            "--deepseek-login, feche outras instâncias desse perfil e instale o Chromium "
                            f"com python -m playwright install chromium. Detalhe: {error}") from error


def _authenticated(page) -> bool:
    return bool(page.evaluate("() => !!localStorage.getItem('userToken')")) and page.locator("textarea").count() > 0


def login(cfg: dict | None = None, settings=None, *, cancel=None, timeout: float = 300) -> dict:
    """Abre a janela e aguarda login/CAPTCHA concluídos pela pessoa."""
    from agent.core.local_policy import refusal

    cfg = {"type": "deepseek_web", "base_url": CHAT_URL, **(cfg or {})}
    blocked = refusal(settings, "deepseek_web", cfg, what="o login")
    if blocked:
        raise ProviderError(blocked)
    with _session_lock(cfg):
        with _browser_page(cfg, visible=True) as page:
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if cancel is not None and cancel.is_set():
                    return {"ok": False, "cancelled": True}
                if _authenticated(page):
                    return {"ok": True, "profile_dir": str(profile_dir(cfg))}
                page.wait_for_timeout(250)
    raise ProviderError("O login do DeepSeek não terminou no prazo. Execute --deepseek-login novamente.")


def serialize_messages(messages: list[dict]) -> str:
    """Mantém papéis e resultados de ferramentas no formato textual do site."""
    pieces = []
    for message in messages:
        item = {key: message[key] for key in ("role", "content", "name", "tool_call_id", "tool_calls")
                if key in message}
        if message.get("images"):
            raise ProviderError("DeepSeek Web: imagens ainda não são enviadas por este conector. "
                                "Escolha um provedor com visão para esse anexo.")
        pieces.append(json.dumps(item, ensure_ascii=False))
    return "Histórico da conversa em JSONL. Responda à última mensagem do usuário:\n" + "\n".join(pieces)


class _Completion:
    """Reconstrói os fragmentos tipados do SSE sem misturar raciocínio e resposta."""

    def __init__(self):
        self.fragments: list[dict] = []
        self.path = ""

    def feed(self, lines: list[str]) -> list[tuple[str, str]]:
        output = []
        for line in lines:
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                item = json.loads(raw)
            except ValueError as error:
                raise ProviderError("DeepSeek Web retornou um quadro SSE inválido.") from error
            if not isinstance(item, dict):
                continue
            if item.get("type") == "error":
                raise ProviderError("DeepSeek Web: " + str(item.get("content") or "falha de geração"))
            value = item.get("v")
            self.path = item.get("p", self.path)
            response = value.get("response") if isinstance(value, dict) else None
            if isinstance(response, dict):
                self.fragments = [dict(f) for f in response.get("fragments", [])]
                for fragment in self.fragments:
                    if fragment.get("content"):
                        output.append((self._kind(fragment), str(fragment["content"])))
                continue
            if self.path.endswith("fragments") and isinstance(value, list):
                self.fragments.extend(dict(f) for f in value)
                for fragment in value:
                    if fragment.get("content"):
                        output.append((self._kind(fragment), str(fragment["content"])))
            elif "/fragments/" in self.path and self.path.endswith("/content") and isinstance(value, str):
                try:
                    index = int(self.path.split("/fragments/", 1)[1].split("/", 1)[0])
                    fragment = self.fragments[index]
                except (ValueError, IndexError):
                    raise ProviderError("DeepSeek Web mudou o formato dos fragmentos da resposta.")
                fragment["content"] = fragment.get("content", "") + value
                output.append((self._kind(fragment), value))
        return output

    @staticmethod
    def _kind(fragment: dict) -> str:
        return "reasoning" if fragment.get("type") in {"THINK", "THINKING", "REASONING"} else "text"


class DeepSeekWebProvider(Provider):
    supports_native_tools = False

    def supports_vision(self, model: str) -> bool:
        return False

    def list_models(self) -> list[str]:
        return list(self.cfg.get("models") or MODELS)

    @_coordinated_inference
    def chat(self, model, messages, tools=None, *, temperature=None, max_tokens=None,
             on_text=None, on_reasoning=None, cancel=None, **extra) -> ChatResult:
        if tools:
            raise ToolsUnsupported("DeepSeek Web usa ferramentas por prompt.")
        if model not in MODELS:
            raise ProviderError(f"Modelo DeepSeek Web desconhecido: {model}. Use {', '.join(MODELS)}.")
        prompt = serialize_messages(messages)
        result = ChatResult()
        lock = _session_lock(self.cfg)
        while not lock.acquire(timeout=0.1):
            if cancel is not None and cancel.is_set():
                return ChatResult(stop_reason="cancelled")
        try:
            if cancel is not None and cancel.is_set():
                return ChatResult(stop_reason="cancelled")
            with _browser_page(self.cfg) as page:
                if not _authenticated(page):
                    raise ProviderError("Faça login na sua conta com --deepseek-login antes de usar DeepSeek Web.")
                try:
                    return self._generate(page, model, prompt, result, on_text, on_reasoning, cancel)
                finally:
                    if _option(self.cfg, "delete_remote_chat", "ORBITA_DEEPSEEK_DELETE_CHAT"):
                        self._delete_own_chat(page, result, on_text)
        finally:
            lock.release()

    def _generate(self, page, model, prompt, result, on_text, on_reasoning, cancel):
        page.evaluate(_OBSERVE_STREAM)
        page.evaluate("options => Object.assign(window.__orbitaDeepSeek, options)",
                      {"model": model.removesuffix("-thinking"), "thinking": model.endswith("-thinking"),
                       "search": _option(self.cfg, "search_enabled", "ORBITA_DEEPSEEK_WEB_SEARCH")})
        editor = page.locator("textarea").first
        editor.fill(prompt)
        editor.press("Enter")
        parser = _Completion()
        deadline = time.monotonic() + max(1, float(self.cfg.get("timeout", 300)))
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                result.stop_reason = "cancelled"
                return result
            frame = page.evaluate(_DRAIN)
            if frame.get("error"):
                raise ProviderError("DeepSeek Web: " + frame["error"])
            for kind, text in parser.feed(frame.get("lines", [])):
                if kind == "reasoning":
                    result.reasoning += text
                    if on_reasoning:
                        on_reasoning(text)
                else:
                    result.text += text
                    if on_text:
                        on_text(text)
            if frame.get("done"):
                if not result.text and not result.reasoning:
                    raise ProviderError("DeepSeek Web encerrou sem devolver uma resposta.")
                result.stop_reason = "stop"
                return result
            page.wait_for_timeout(100)
        raise ProviderError("DeepSeek Web demorou além do limite; a geração foi interrompida.")

    @staticmethod
    def _delete_own_chat(page, result, on_text):
        try:
            outcome = page.evaluate(_DELETE_OWN_CHAT)
            if not isinstance(outcome, dict):
                outcome = {"ok": False, "error": "O navegador não confirmou a exclusão."}
        except Exception as error:
            outcome = {"ok": False, "error": str(error)}
        result.native = {"deepseek_web": {"remote_chat_deleted": bool(outcome.get("ok")),
                                          "delete_error": outcome.get("error", "")}}
        if not outcome.get("ok"):
            warning = "\n\n[Não consegui apagar a conversa no DeepSeek: " + outcome.get("error", "erro desconhecido") + "]"
            result.text += warning
            if on_text:
                on_text(warning)
