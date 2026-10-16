/* Órbita — interface (JS puro, sem dependências externas). Fala com o Python via QWebChannel. */
"use strict";

// ── Ícones (traços 24x24, desenhados para este app) ───────────────────────────
const ICONS = {
  chat: "M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H9l-5 4z",
  users: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21v-1a6 6 0 0 1 12 0v1M16 3.6a4 4 0 0 1 0 6.8M22 21v-1a6 6 0 0 0-4-5.6",
  plug: "M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5",
  settings: "M4 7h9M17 7h3M4 17h3M11 17h9M15 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM9 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  command: "M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  plus: "M12 5v14M5 12h14",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3",
  sidebar: "M3 5h18v14H3zM9 5v14",
  panel: "M3 5h18v14H3zM15 5v14",
  chevdown: "M6 9l6 6 6-6",
  chevright: "M9 6l6 6-6 6",
  cpu: "M7 7h10v10H7zM10 10h4v4h-4zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3",
  clip: "M21 11.5l-8.6 8.6a5.2 5.2 0 0 1-7.4-7.4l8.6-8.6a3.5 3.5 0 0 1 5 5l-8.6 8.5a1.8 1.8 0 0 1-2.5-2.5l7.9-7.9",
  mic: "M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  send: "M12 19V5M5 12l7-7 7 7",
  stop: "M7 7h10v10H7z",
  x: "M6 6l12 12M18 6L6 18",
  check: "M5 12.5l4.5 4.5L19 7",
  alert: "M12 8v5M12 16.5v.5M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8v.5",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  folder: "M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
  file: "M6 3h8l4 4v14H6zM14 3v4h4",
  term: "M4 5h16v14H4zM8 10l3 2-3 2M13 15h4",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18",
  edit2: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  image: "M3 5h18v14H3zM3 16l5-5 4 4 3-3 6 6M15.5 9.5h.01",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  book: "M4 4.5h6a3 3 0 0 1 3 3V20a2 2 0 0 0-2-2H4zM20 4.5h-4a3 3 0 0 0-3 3V20a2 2 0 0 1 2-2h5z",
  brain: "M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a3 3 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  key: "M8 15a4 4 0 1 0 0 .01M11 12l9-9M16 7l3 3M18 5l2 2",
  coins: "M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  wave: "M2 12h3l3-8 4 16 3-8h7",
  download: "M12 4v12M6 10l6 6 6-6M4 20h16",
  refresh: "M20 11a8 8 0 0 0-14.6-4.5L4 8M4 3v5h5M4 13a8 8 0 0 0 14.6 4.5L20 16M20 21v-5h-5",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  code: "M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14",
  user: "M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM4 21a8 8 0 0 1 16 0",
  mouse: "M12 3a6 6 0 0 1 6 6v6a6 6 0 0 1-12 0V9a6 6 0 0 1 6-6zM12 7v3",
  layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
  undo: "M9 14L4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11",
  redo: "M15 14l5-5-5-5M20 9H9.5a5.5 5.5 0 0 0 0 11H13",
  map: "M9 4L3 6v14l6-2 6 2 6-2V4l-6 2zM9 4v14M15 6v14",
  at: "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0zM16 12v1.5a2.5 2.5 0 0 0 5 0V12a9 9 0 1 0-3.5 7.1",
  diff: "M6 3h8l4 4v14H6zM9 11h6M12 8v6M9 17h6",
  pin: "M12 17v5M9 3h6l-1 6 3 3v2H7v-2l3-3z",
};
// ── Ícones dos agentes: símbolo próprio sobre degradê (substituem os emojis do Windows) ──
const S_ = 'stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" fill="none"';
const F_ = 'fill="#fff"';
const AGENT_ICONS = {
  spark: { label: "Órbita", a: "#22d3ee", b: "#a855f7", svg:
    `<ellipse cx="12" cy="12.5" rx="9.6" ry="3.8" transform="rotate(-24 12 12.5)" ${S_} opacity=".65"/>
     <path d="M12 3.6c.7 4.3 2.3 5.9 6.6 6.6-4.3.7-5.9 2.3-6.6 6.6-.7-4.3-2.3-5.9-6.6-6.6 4.3-.7 5.9-2.3 6.6-6.6z" ${F_}/>
     <circle cx="18.6" cy="6" r="1.3" ${F_}/>` },
  lead: { label: "Liderança", a: "#f59e0b", b: "#ef4444", svg:
    `<circle cx="12" cy="5.5" r="2.4" ${F_}/><path d="M12 8v3.5M5.5 15.5v-2a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v2M12 11.5v4" ${S_}/>
     <circle cx="5.5" cy="18" r="2.1" ${S_}/><circle cx="12" cy="18" r="2.1" ${S_}/><circle cx="18.5" cy="18" r="2.1" ${S_}/>` },
  code: { label: "Código", a: "#3b82f6", b: "#06b6d4", svg:
    `<path d="M8.5 7.5 4 12l4.5 4.5M15.5 7.5 20 12l-4.5 4.5" ${S_} stroke-width="2"/><path d="M13.4 5.5l-2.8 13" ${S_} opacity=".8"/>` },
  review: { label: "Revisão", a: "#10b981", b: "#0d9488", svg:
    `<circle cx="10.5" cy="10.5" r="6.2" ${S_}/><path d="m15.2 15.2 4.6 4.6" ${S_} stroke-width="2.2"/>
     <path d="m7.9 10.6 1.9 1.9 3.4-3.6" ${S_} stroke-width="1.9"/>` },
  research: { label: "Pesquisa", a: "#0ea5e9", b: "#6366f1", svg:
    `<circle cx="11" cy="13" r="7.2" ${S_}/><path d="M3.8 13h14.4M11 5.8c2.2 2.2 2.2 12.2 0 14.4M11 5.8c-2.2 2.2-2.2 12.2 0 14.4" ${S_} opacity=".75"/>
     <circle cx="19" cy="5" r="1.7" ${F_}/><path d="M17.6 6.4 15.9 8" ${S_} opacity=".7"/>` },
  design: { label: "Criação", a: "#ec4899", b: "#f97316", svg:
    `<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.1 0 1.7-.8 1.7-1.7 0-1.2-1-1.6-1-2.7 0-.9.8-1.5 1.7-1.5h2.3a3.8 3.8 0 0 0 3.8-3.8c0-4.1-3.8-7.3-8.5-7.3z" ${S_}/>
     <circle cx="7.6" cy="11" r="1.25" ${F_}/><circle cx="9.9" cy="7.3" r="1.25" ${F_}/><circle cx="14.3" cy="7.3" r="1.25" ${F_}/><circle cx="16.9" cy="10.6" r="1.25" ${F_}/>` },
  reverse: { label: "Engenharia reversa", a: "#a855f7", b: "#d946ef", svg:
    `<path d="M7.5 3c0 4.6 9 4.4 9 9s-9 4.4-9 9M16.5 3c0 4.6-9 4.4-9 9s9 4.4 9 9" ${S_}/>
     <path d="M9 6.2h6M9.4 17.8h5.2" ${S_} opacity=".7"/>` },
  bolt: { label: "Agente externo", a: "#facc15", b: "#f97316", svg:
    `<path d="M13.6 2.8 5.2 13.4h5.9l-1 7.8 8.7-11h-6z" ${F_}/>` },
  cursor: { label: "Automação", a: "#14b8a6", b: "#22c55e", svg:
    `<path d="M4 6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v4.5M4 6v8a2 2 0 0 0 2 2h4.5M4 8h14" ${S_}/>
     <path d="m13 12.2 7.6 2.9-3.3 1.3-1.3 3.3z" ${F_}/>` },
  bot: { label: "Agente", a: "#64748b", b: "#6366f1", svg:
    `<rect x="4.5" y="8" width="15" height="11" rx="3" ${S_}/><path d="M12 4.5V8" ${S_}/><circle cx="12" cy="4" r="1.2" ${F_}/>
     <circle cx="9.3" cy="13.2" r="1.3" ${F_}/><circle cx="14.7" cy="13.2" r="1.3" ${F_}/>` },
};
// Perfis salvos antes trazem emoji: continuam funcionando, agora com o ícone novo.
const EMOJI_TO_ICON = { "✨": "spark", "🧠": "lead", "💻": "code", "🔍": "review", "🌐": "research", "🎨": "design",
                        "🧬": "reverse", "⚡": "bolt", "🖱️": "cursor", "🖱": "cursor", "🤖": "bot" };
function agentIconKey(value) {
  const v = String(value || "").trim();
  return AGENT_ICONS[v] ? v : (EMOJI_TO_ICON[v] || (v ? null : "bot"));
}
function agentIcon(p, size = 40) {
  const key = agentIconKey(p && p.icon);
  if (!key) return `<span class="agent-ic emoji" style="--s:${size}px">${esc(p.icon)}</span>`;  // emoji escolhido pelo usuário
  const ic = AGENT_ICONS[key];
  return `<span class="agent-ic" style="--s:${size}px;--a:${ic.a};--b:${ic.b}" title="${esc(ic.label)}"><svg viewBox="0 0 24 24">${ic.svg}</svg></span>`;
}

function icon(name, cls = "i") {
  return `<svg class="${cls}" viewBox="0 0 24 24"><path d="${ICONS[name] || ICONS.sparkle}"/></svg>`;
}
function hydrateIcons(root = document) {
  root.querySelectorAll("svg[data-ic]").forEach(svg => {
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.innerHTML = `<path d="${ICONS[svg.dataset.ic] || ""}"/>`;
  });
}

// ── Utilidades ─────────────────────────────────────────────────────────────────
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fileUrl = p => "file:///" + String(p).replace(/\\/g, "/").split("/").map(encodeURIComponent).join("/").replace(/^file:\/\/\/([A-Za-z])%3A/, "file:///$1:");
const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n || 0);
const now = () => new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

let api = null;
let S = {};              // estado vindo do Python
let busy = false, attachments = [], liveTimer = null, liveStart = 0, planMode = false, longHintShown = false;
let turnEl = null, segEls = {}, stepEls = {}, stepsBox = null;
let settingsSection = "geral";

function call(method, ...args) {
  return new Promise(resolve => {
    if (!api) return resolve(null);
    api[method](...args, raw => {
      try { resolve(raw ? JSON.parse(raw) : null); } catch { resolve(raw); }
    });
  });
}

// ── Inicialização ──────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  hydrateIcons();
  new QWebChannel(qt.webChannelTransport, async channel => {
    api = channel.objects.api;
    api.message.connect(raw => onEvent(JSON.parse(raw)));
    S = await call("getState");
    $("#pygments").textContent = S.pygments_css || "";
    applyTheme(S.settings.theme || "dark");
    renderAll();
    if (!S.settings.onboarded) showOnboarding();
  });
  bindChrome();
});

function renderAll() {
  renderTopbar(); renderConvs(); renderWelcome(); renderAgents(); renderQuick();
  $("#avatar").textContent = (S.settings.user_name || "?").trim().charAt(0).toUpperCase() || "?";
  $("#mcp-dot").classList.toggle("on", (S.mcp || []).some(s => s.status === "erro"));
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('[data-action="theme"] svg').dataset.ic = theme === "dark" ? "moon" : "sun";
  hydrateIcons($("#rail"));
}

// ── Navegação e atalhos ────────────────────────────────────────────────────────
function go(page) {
  $$(".page").forEach(p => p.classList.toggle("active", p.id === "page-" + page));
  $$(".rail-btn[data-go]").forEach(b => b.classList.toggle("active", b.dataset.go === page));
  if (page === "team") renderTeamPage();
  if (page === "connections") renderConnections();
  if (page === "settings") renderSettings();
  if (page === "chat") setTimeout(() => $("#input").focus(), 30);
}

function bindChrome() {
  document.addEventListener("click", e => {
    if (!e.target.closest("#ctx-menu")) closeCtxMenu();
    const goEl = e.target.closest("[data-go]");
    if (goEl) return go(goEl.dataset.go);
    const act = e.target.closest("[data-action]");
    if (act) return action(act.dataset.action, act);
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      const code = copy.closest(".code").querySelector("code").innerText;
      call("copyText", code); copy.textContent = "Copiado ✓"; setTimeout(() => copy.textContent = "Copiar", 1400);
    }
    const img = e.target.closest(".zoomable");
    if (img) lightbox(img.src);
    const link = e.target.closest("a[href]");
    if (link && !link.closest("[data-go]")) { e.preventDefault(); call("openUrl", link.getAttribute("href")); }
  });
  const input = $("#input");
  input.addEventListener("input", () => { autosize(); slashHint(); mentionHint(); });
  input.addEventListener("keydown", e => {
    if (mentionKey(e)) return;
    if (dict && e.key === "Enter") { e.preventDefault(); stopDictation(); return; }   // Enter termina o ditado, não envia
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  input.addEventListener("blur", () => setTimeout(closeMention, 150));
  $("#plan-btn").addEventListener("click", () => setPlanMode(!planMode));
  $("#send").addEventListener("click", () => busy ? call("stop") : send());
  document.addEventListener("keydown", e => {
    if (e.ctrlKey && e.key.toLowerCase() === "k") { e.preventDefault(); palette(); }
    else if (e.ctrlKey && e.key.toLowerCase() === "n") { e.preventDefault(); action("new"); }
    else if (e.ctrlKey && e.key.toLowerCase() === "b") { e.preventDefault(); action("toggle-side"); }
    else if (e.ctrlKey && e.key === ",") { e.preventDefault(); go("settings"); }
    else if (e.key === "Escape" && dict) { e.preventDefault(); cancelDictation(); }
    else if (e.ctrlKey && e.key.toLowerCase() === "m") { e.preventDefault(); toggleDictation(); }
    else if (e.key === "Escape") { if ($("#ctx-menu").innerHTML) closeCtxMenu(); else if ($("#modal-root").innerHTML) closeModal(); else if (busy) call("stop"); }
  });
  $("#conv-search").addEventListener("input", renderConvs);
  $("#conv-list").addEventListener("scroll", closeCtxMenu);
  const title = $("#conv-title");
  title.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); title.blur(); }
    else if (e.key === "Escape") { e.preventDefault(); title.textContent = S.conversation_title || "Nova conversa"; title.blur(); }
  });
  title.addEventListener("blur", () => {
    const t = title.textContent.trim();
    if (S.conversation_id && t) { S.conversation_title = t; call("renameConversation", S.conversation_id, t).then(refreshConvs); }
    else title.textContent = S.conversation_title || "Nova conversa";
  });
  $("#chip-pin").addEventListener("click", pinnedPromptModal);
  $("#pin-banner").addEventListener("click", pinnedPromptModal);
  $("#chip-profile").addEventListener("click", profileMenu);
  $("#chip-project").addEventListener("click", () => projectDialog());
  $("#chip-model").addEventListener("click", modelMenu);
  $("#chip-perm").addEventListener("click", cyclePermission);
  $("#compact-btn").addEventListener("click", compactConversation);
  $("#dict-done").addEventListener("click", stopDictation);
  $("#dict-cancel").addEventListener("click", cancelDictation);
  $$(".tab").forEach(t => t.addEventListener("click", () => selectTab(t.dataset.tab)));
  const box = $("#composer-box");
  box.addEventListener("dragover", e => { e.preventDefault(); box.classList.add("drag"); });
  box.addEventListener("dragleave", () => box.classList.remove("drag"));
  box.addEventListener("drop", async e => {
    e.preventDefault(); box.classList.remove("drag");
    const paths = [...e.dataTransfer.files].map(f => f.path || "").filter(Boolean);
    if (!paths.length) {  // QtWebEngine não expõe o caminho: usa a URI
      const uris = (e.dataTransfer.getData("text/uri-list") || "").split(/\r?\n/).filter(u => u.startsWith("file:"));
      uris.forEach(u => paths.push(decodeURIComponent(u.replace(/^file:\/\/\/?/, ""))));
    }
    addAttachments(paths);
  });
}

async function action(name, el) {
  switch (name) {
    case "new": await call("newConversation"); resetChat(); refreshConvs(); break;
    case "toggle-side": $("#side").classList.toggle("hidden"); break;
    case "toggle-convs": $("#page-chat").classList.toggle("no-convs"); break;
    case "attach": addAttachments(await call("pickImages") || []); break;
    case "voice": if (!busy) call("voice"); break;
    case "dictate": toggleDictation(); break;
    case "theme": {
      const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(t); call("setSetting", "theme", JSON.stringify(t)); break;
    }
    case "palette": palette(); break;
  }
}

function selectTab(name) {
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tabpane").forEach(p => p.classList.toggle("active", p.id === name));
  $("#side").classList.remove("hidden");
}

function autosize() { const i = $("#input"); i.style.height = "auto"; i.style.height = Math.min(i.scrollHeight, 220) + "px"; }

// ── Topo do chat ───────────────────────────────────────────────────────────────
function renderTopbar() {
  const p = S.profile || {};
  $("#profile-ic").innerHTML = agentIcon(p, 20);
  $("#profile-name").textContent = p.name || "Perfil";
  $("#project-name").textContent = S.workspace_set ? (S.workspace_name || "Projeto") : "Abrir projeto";
  $("#chip-project").classList.toggle("need", !S.workspace_set);
  $("#chip-project").title = S.workspace_set ? ("Projeto: " + (S.workspace || "")) : "Escolher ou criar a pasta do projeto";
  $("#model-name").textContent = S.model_label || "";
  const perm = S.settings.permission_mode;
  $("#perm-name").textContent = { perguntar: "Perguntar", auto: "Auto", livre: "Livre" }[perm] || perm;
  $("#chip-perm").className = "chip perm-" + perm;
  $("#conv-title").textContent = S.conversation_title || "Nova conversa";
  const pin = (S.pinned_prompt || "").trim();
  $("#chip-pin").classList.toggle("on", !!pin);
  $("#chip-pin").title = pin ? ("Prompt da conversa: " + pin.slice(0, 140)) : "Definir instruções fixas para esta conversa";
  $("#pin-badge").hidden = !pin;
  const banner = $("#pin-banner");
  if (banner) {
    banner.hidden = !pin;
    banner.innerHTML = pin ? `${icon("pin")}<b>Prompt da conversa</b><span class="txt">${esc(pin.replace(/\s+/g, " "))}</span><span class="pin-badge">ativo</span>` : "";
  }
  updateMeter(S.conversation_tokens || 0);
}
function pinnedPromptModal() {
  const current = (S.pinned_prompt || "").trim();
  openModal(`<div class="modal"><div class="row" style="justify-content:space-between"><h2 style="margin:0">${icon("pin")} Prompt da conversa</h2>
      <button class="icon-btn" id="pin-close" title="Fechar (Esc)">${icon("x")}</button></div>
    <p class="sub" style="margin-top:6px">Instruções fixas aplicadas em todos os turnos desta conversa, além do prompt do perfil.</p>
    <textarea class="inp" id="pin-text" style="min-height:130px" placeholder="Ex.: Responda sempre em tópicos curtos, use Python 3.10 e não altere arquivos fora de src/…">${esc(current)}</textarea>
    <div class="actions">
      <button class="btn danger" id="pin-remove" ${current ? "" : "disabled"}>${icon("trash")} Remover</button>
      <span style="flex:1"></span>
      <button class="btn" id="pin-cancel">Cancelar</button>
      <button class="btn primary" id="pin-save">${icon("check")} Salvar</button>
    </div></div>`);
  $("#pin-close").onclick = closeModal;
  $("#pin-cancel").onclick = closeModal;
  const applyPin = async text => {
    const r = await call("setPinnedPrompt", text);
    S.pinned_prompt = (r && r.pinned_prompt) || "";
    closeModal();
    renderTopbar();
    toast("success", "Prompt da conversa", S.pinned_prompt ? "Instruções fixas ativadas nesta conversa." : "Prompt da conversa removido.", 2400);
  };
  $("#pin-save").onclick = () => applyPin($("#pin-text").value.trim());
  $("#pin-remove").onclick = () => applyPin("");
}
function updateMeter(tokens) {
  const budget = S.settings.turn_token_budget || 0;
  $("#meter-txt").textContent = fmt(tokens) + (budget ? " / " + fmt(budget) : "");
  $("#meter-bar").style.width = budget ? Math.min(100, tokens / budget * 100) + "%" : "0";
}
async function cyclePermission() {
  const order = ["perguntar", "auto", "livre"];
  const next = order[(order.indexOf(S.settings.permission_mode) + 1) % 3];
  S = await call("setSetting", "permission_mode", JSON.stringify(next));
  renderTopbar();
  toast("info", "Permissões", { perguntar: "Vai perguntar antes de qualquer alteração.", auto: "Pergunta só para executar comandos e controlar o PC.", livre: "Age com total liberdade, sem perguntar." }[next]);
}
function profileMenu() {
  openModal(`<div class="modal palette"><input id="pf-q" placeholder="Trocar perfil…"><div class="opts">${
    S.profiles.map(p => `<div class="opt" data-id="${esc(p.id)}">${agentIcon(p, 34)}<div><b>${esc(p.name)}</b><div style="font-size:12px">${esc(p.description)}</div></div>${p.id === S.profile.id ? icon("check") : ""}</div>`).join("")
  }</div></div>`);
  $$(".opt", $("#modal-root")).forEach(o => o.addEventListener("click", async () => {
    S = await call("selectProfile", o.dataset.id); closeModal(); renderAll();
    toast("success", "Perfil ativo", `${S.profile.name} · ${S.model_label}`);
  }));
  filterOpts("#pf-q");
}

// Troca rápida de modelo pelo topo: lista os modelos da API (busca no provedor se ainda não tiver a lista).
let quickModelList = null;
function modelMenu() {
  const usable = S.providers.filter(p => p.has_credentials || p.id === S.provider);
  openModal(`<div class="modal palette model-menu">
    <div class="mm-head"><select class="inp" id="mm-prov" title="Provedor">${usable.map(p => `<option value="${esc(p.id)}" ${p.id === S.provider ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select>
      <input id="mm-q" placeholder="Buscar modelo…" spellcheck="false" autocomplete="off">
      <button class="icon-btn" id="mm-refresh" title="Buscar a lista de modelos no provedor">${icon("refresh")}</button></div>
    <div class="model-pick mm-list" id="mm-list"></div>
    <div class="mm-foot"><span id="mm-hint"></span><button class="btn small" id="mm-settings">${icon("settings")} Configurações › Modelos</button></div>
  </div>`);
  const prov = $("#mm-prov");
  const pick = async model => {
    const res = await call("selectModel", prov.value, model);
    if (!res || res.error) return toast("error", "Modelo", (res && res.error) || "Não deu para usar esse modelo.", 7000);
    S = res.state; closeModal(); renderAll();
    toast("success", "Modelo ativo", S.model_label + (res.bound_profile ? ` · perfil ${res.bound_profile}` : ""));
  };
  quickModelList = bindSearchableModels({
    provEl: prov, modelEl: document.createElement("input"), searchEl: $("#mm-q"), listEl: $("#mm-list"),
    hintEl: $("#mm-hint"), refreshBtn: $("#mm-refresh"),
    isActive: (provId, m) => S.provider === provId && S.model === m, onPick: pick,
  });
  const fetchOnce = () => {   // lista completa da API uma vez por sessão; depois abre na hora
    if (!prov.value || quickFetched.has(prov.value)) return;
    quickFetched.add(prov.value);
    call("refreshModels", prov.value);
  };
  prov.addEventListener("change", fetchOnce);
  fetchOnce();
  $("#mm-settings").onclick = () => { closeModal(); settingsSection = "modelos"; go("settings"); };
  $("#mm-q").focus();
}
const quickFetched = new Set();

// ── Conversas ──────────────────────────────────────────────────────────────────
async function refreshConvs() { S.conversations = await call("listConversations"); renderConvs(); }
function closeCtxMenu() { const box = $("#ctx-menu"); if (box) box.innerHTML = ""; }
function openConvMenu(id, x, y) {
  const box = $("#ctx-menu");
  const cx = Math.min(x, window.innerWidth - 190), cy = Math.min(y, window.innerHeight - 100);
  box.innerHTML = `<div class="ctx-menu" style="left:${cx}px;top:${cy}px">
    <button type="button" class="ctx-item" data-ctx="rename">${icon("edit")}<span>Renomear</span></button>
    <button type="button" class="ctx-item danger" data-ctx="delete">${icon("trash")}<span>Apagar</span></button>
  </div>`;
  $('[data-ctx="rename"]', box).onclick = () => { closeCtxMenu(); startRenameConv(id); };
  $('[data-ctx="delete"]', box).onclick = () => { closeCtxMenu(); deleteConvWithConfirm(id); };
}
async function deleteConvWithConfirm(id) {
  if (!(await confirmBox("Apagar conversa?", "Ela será removida deste computador.", "Apagar"))) return;
  await call("deleteConversation", id);
  if (id === S.conversation_id) { await call("newConversation"); resetChat(); }
  refreshConvs();
}
function startRenameConv(id) {
  const row = $(`.conv[data-id="${CSS.escape(id)}"]`, $("#conv-list"));
  if (!row) return;
  const tEl = $(".t", row), delBtn = $(".x", row);
  if (!tEl) return;
  const oldTitle = ((S.conversations || []).find(c => c.id === id)?.title) || tEl.textContent || "";
  const inp = document.createElement("input");
  inp.className = "rename-inp";
  inp.value = oldTitle;
  inp.spellcheck = false;
  if (delBtn) delBtn.style.display = "none";
  tEl.replaceWith(inp);
  inp.focus();
  inp.select();
  let finished = false;
  const finish = async save => {
    if (finished) return;
    finished = true;
    const val = inp.value.trim().slice(0, 80);
    if (save && val && val !== oldTitle) {
      await call("renameConversation", id, val);
      if (id === S.conversation_id) {
        S.conversation_title = val;
        $("#conv-title").textContent = val;
      }
      await refreshConvs();
    } else {
      renderConvs();
    }
  };
  inp.addEventListener("click", e => e.stopPropagation());
  inp.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
  });
  inp.addEventListener("blur", () => finish(false));
}
function renameCurrentConv() {
  go("chat");
  if (S.conversation_id && !$("#page-chat").classList.contains("no-convs") && $(`.conv[data-id="${CSS.escape(S.conversation_id)}"]`, $("#conv-list"))) {
    startRenameConv(S.conversation_id);
  } else {
    const t = $("#conv-title");
    t.focus();
    const range = document.createRange();
    range.selectNodeContents(t);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }
}
function renderConvs() {
  const q = ($("#conv-search").value || "").toLowerCase();
  const items = (S.conversations || []).filter(c => !q || c.title.toLowerCase().includes(q));
  const groups = {};
  const localDay = ms => { const d = new Date(ms); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const today = localDay(Date.now()), yest = localDay(Date.now() - 864e5), week = localDay(Date.now() - 7 * 864e5);
  items.forEach(c => {
    const d = (c.updated || "").slice(0, 10);
    const g = d === today ? "Hoje" : d === yest ? "Ontem" : d >= week ? "Últimos 7 dias" : "Mais antigas";
    (groups[g] = groups[g] || []).push(c);
  });
  const html = Object.entries(groups).map(([g, list]) => `<div class="conv-group">${g}</div>` + list.map(c =>
    `<div class="conv ${c.id === S.conversation_id ? "active" : ""}" data-id="${esc(c.id)}">${icon("chat")}<span class="t">${esc(c.title)}</span><button class="x" data-del="${esc(c.id)}" title="Apagar">${icon("trash")}</button></div>`).join("")).join("");
  $("#conv-list").innerHTML = html || `<div class="empty">Nenhuma conversa ainda.<br>Elas aparecem aqui automaticamente.</div>`;
  $$(".conv", $("#conv-list")).forEach(el => {
    el.addEventListener("contextmenu", e => {
      e.preventDefault();
      e.stopPropagation();
      openConvMenu(el.dataset.id, e.clientX, e.clientY);
    });
    el.addEventListener("click", async e => {
      if (e.target.closest(".rename-inp")) return;
      const del = e.target.closest("[data-del]");
      if (del) {
        e.stopPropagation();
        deleteConvWithConfirm(del.dataset.del);
        return;
      }
      if (busy) return toast("warn", "Aguarde", "O agente ainda está trabalhando nesta conversa.");
      openConversation(el.dataset.id);
    });
  });
}
async function openConversation(id) {
  const data = await call("openConversation", id);
  if (!data) return toast("error", "Conversa", "Não foi possível abrir.");
  resetChat(false);
  S.conversation_id = data.id; S.conversation_title = data.title; S.pinned_prompt = data.pinned_prompt || "";
  renderTopbar(); renderConvs();
  data.blocks.forEach(b => {
    if (b.kind === "user") addUser(b.text, b.images);
    else if (b.kind === "assistant") { ensureTurn(data.model_label); segment("h" + Math.random(), b.html, false); }
    else if (b.kind === "tool") { ensureTurn(data.model_label); toolStep({ ...b, id: "h" + Math.random() }); }
  });
  closeTurn();
  scrollEnd(true);
}

// ── Chat ───────────────────────────────────────────────────────────────────────
function resetChat(welcome = true) {
  $("#messages").innerHTML = ""; turnEl = null; segEls = {}; stepEls = {}; stepsBox = null; longHintShown = false; undoNote = "";
  S.conversation_id = null; S.conversation_title = ""; S.pinned_prompt = ""; S.conversation_tokens = 0;
  $("#feed").innerHTML = `<div class="empty">As ações do agente aparecem aqui em tempo real.</div>`;
  renderTopbar(); renderConvs();
  if (welcome) renderWelcome();
}
function renderWelcome() {
  if ($("#messages").children.length && !$(".welcome")) return;
  const name = (S.settings.user_name || "").split(" ")[0];
  const cards = [
    ["code", "Analisar um projeto", "Leia o projeto na minha pasta de trabalho e me diga a estrutura, problemas e próximos passos."],
    ["globe", "Pesquisar a fundo", "Pesquise na web e compare as melhores opções para "],
    ["users", "Trabalho em equipe", "Divida esta tarefa entre a equipe, em paralelo, e depois revise tudo: "],
    ["folder", "Organizar arquivos", "Organize os arquivos da pasta Downloads por tipo e me mostre o resultado."],
    ["mouse", "Controlar o PC", "Tire um screenshot e me diga o que está aberto na tela."],
    ["layers", "Engenharia reversa", "Analise com o REA o executável "],
  ];
  const project = S.workspace_set ? (S.workspace || "") : "";
  $("#messages").innerHTML = `<div class="welcome"><img class="orb" src="logo.svg" alt="">
    <h1>${name ? `Olá, <span>${esc(name)}</span>` : `<span>Órbita</span>`}</h1>
    <p class="who-line">${agentIcon(S.profile, 22)} ${esc(S.profile?.name || "")} · ${esc(S.model_label || "")} — o que vamos fazer hoje?</p>
    <div class="project-banner"><div class="txt"><b>${project ? "Projeto aberto" : "Nenhum projeto aberto"}</b><span>${project ? esc(project) : "Escolha ou crie a pasta em que o agente vai trabalhar."}</span></div><button class="btn primary" id="welcome-project">${icon("folder")} ${project ? "Trocar projeto" : "Abrir ou criar projeto"}</button></div>
    <div class="cards">${cards.map(([ic, t, p]) => `<div class="card" data-prompt="${esc(p)}"><div class="ci">${icon(ic)}</div><b>${t}</b><span>${esc(p.length > 70 ? p.slice(0, 70) + "…" : p)}</span></div>`).join("")}</div></div>`;
  const openProject = $("#welcome-project");
  if (openProject) openProject.addEventListener("click", () => projectDialog());
  $$(".card", $("#messages")).forEach(c => c.addEventListener("click", () => {
    const i = $("#input"); i.value = c.dataset.prompt; i.focus(); autosize();
    i.setSelectionRange(i.value.length, i.value.length);
  }));
}
function renderQuick() {
  const box = $("#quick");
  const items = S.quick_prompts || [];
  box.innerHTML = items.map(q => `<button data-q="${esc(q.text)}">${esc(q.label)}</button>`).join("");
  $$("button", box).forEach(b => b.addEventListener("click", () => { $("#input").value = b.dataset.q; autosize(); $("#input").focus(); }));
}
function slashHint() {
  const v = $("#input").value;
  if (v === "/") palette("");
}
let undoNote = "";   // avisa o agente, na próxima mensagem, que o usuário desfez arquivos
function send(override) {
  const typed = override === undefined;
  const text = (typed ? $("#input").value : override).trim();
  if ((!text && !attachments.length) || busy) return;
  closeMention();
  if ($(".welcome")) $("#messages").innerHTML = "";
  const msg = text || "Analise a imagem anexada.", plan = typed && planMode;
  addUser(msg, attachments, plan);
  call("send", JSON.stringify({ text: msg + undoNote, images: attachments, plan }));
  undoNote = "";
  if (typed) { $("#input").value = ""; autosize(); }
  attachments = []; renderAttachments();
  maybeLongHint();
}
function addUser(text, images = [], plan = false) {
  closeTurn();
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble">${plan ? `<span class="plan-tag">${icon("map")} só planejar</span>` : ""}${esc(text)}${(images || []).map(p => `<img class="zoomable" src="${fileUrl(p)}">`).join("")}</div>`;
  $("#messages").appendChild(el);
  scrollEnd(true);
}
function maybeLongHint() {
  if (longHintShown || $$(".msg.user").length < 14) return;
  longHintShown = true;
  note("Conversa longa: para um assunto novo, comece outra conversa (Ctrl+N). O agente fica mais preciso e gasta menos tokens.", "tip");
}

// ── Ditado: fala vira texto no campo, enquanto se fala ─────────────────────────
let dict = null;   // { before, after, start, timer } enquanto grava
function toggleDictation() { if (dict) stopDictation(); else startDictation(); }
async function startDictation() {
  const i = $("#input");
  dict = { before: i.value.slice(0, i.selectionStart), after: i.value.slice(i.selectionEnd), start: Date.now(), timer: null, text: "" };
  $("#composer-box").classList.add("dictating"); $("#mic").classList.add("rec");
  $("#dict-label").textContent = "Abrindo o microfone…";
  dict.timer = setInterval(() => { if (!dict) return; const s = Math.floor((Date.now() - dict.start) / 1000); $("#dict-time").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }, 250);
  const r = await call("dictationStart");
  if (r && r.error) { endDictation(); toast("warn", "Ditado", r.error); }
}
function stopDictation() { if (!dict) return; $("#dict-label").textContent = "Transcrevendo…"; $("#composer-box").classList.add("finishing"); call("dictationStop"); }
function cancelDictation() { if (!dict) return; call("dictationCancel"); applyDictation(""); endDictation(); }
function applyDictation(text) {
  if (!dict) return;
  const i = $("#input"), b = dict.before, gap = b && !/\s$/.test(b) && text ? " " : "";
  i.value = b + gap + text + dict.after;
  const pos = (b + gap + text).length; i.setSelectionRange(pos, pos); autosize();
}
function endDictation() {
  if (dict) clearInterval(dict.timer);
  dict = null;
  $("#composer-box").classList.remove("dictating", "finishing"); $("#mic").classList.remove("rec");
  $("#input").classList.remove("partial"); $("#input").focus();
}
function renderVoiceGpu(g) {
  const status = $("#vg-status"), btn = $("#vg-install");
  if (!status || !g) return;
  btn.style.display = g.cuda && !g.libs && !g.installing ? "" : "none";
  status.innerHTML = !g.cuda ? "Nenhuma placa NVIDIA encontrada: o ditado usa a CPU (texto parcial em ~1 s)."
    : g.installing ? `<span class="spin" style="display:inline-block;vertical-align:-3px"></span> Instalando as bibliotecas da NVIDIA (~1 GB). Pode continuar usando o programa.`
    : g.libs ? `<span style="color:var(--ok)">● Ditado na placa de vídeo</span>: o texto aparece quase na hora.`
    : "Placa NVIDIA encontrada, mas faltam as bibliotecas CUDA. Instale para o ditado ficar instantâneo (download de ~1 GB, uma vez).";
}
function onDictation(e) {
  if (!dict && e.state !== "error") return;
  switch (e.state) {
    case "recording": $("#dict-label").textContent = "Ouvindo… fale à vontade"; $("#dict-label").title = e.engine ? "Transcrição: " + e.engine : ""; break;
    case "level": $$(".dict-level i").forEach((bar, k) => bar.style.transform = `scaleY(${Math.max(.15, Math.min(1, e.level * (1.4 - Math.abs(k - 3) * .2)))})`); break;
    case "partial": dict.text = e.text; $("#input").classList.add("partial"); applyDictation(e.text); break;
    case "finishing": $("#dict-label").textContent = "Transcrevendo…"; $("#composer-box").classList.add("finishing"); break;
    case "done": $("#input").classList.remove("partial"); applyDictation(e.text || ""); if (!e.text && e.message) toast("warn", "Ditado", e.message); endDictation(); break;
    case "cancelled": endDictation(); break;
    case "error": if (dict) { applyDictation(""); endDictation(); } toast("error", "Microfone", e.message || "O ditado falhou.", 8000); break;
  }
}

// ── Modo plano ─────────────────────────────────────────────────────────────────
function setPlanMode(on) {
  planMode = on;
  $("#plan-btn").classList.toggle("on", on);
  $("#composer-box").classList.toggle("plan", on);
  $("#input").placeholder = on ? "Modo plano: descreva o que quer. O agente só lê, planeja e espera o seu OK."
    : "Peça qualquer coisa… (@ cita um arquivo, / comandos, Shift+Enter quebra linha)";
}
function planActions() {
  const last = $$(".msg.bot").pop();
  if (!last) return;
  const row = document.createElement("div"); row.className = "plan-actions";
  row.innerHTML = `<button class="btn primary small" data-pa="run">${icon("bolt")} Executar plano</button><button class="btn small" data-pa="adjust">${icon("edit")} Ajustar o plano</button>`;
  $('[data-pa="run"]', row).onclick = () => { if (busy) return; setPlanMode(false); row.remove(); send("Pode executar o plano."); };
  $('[data-pa="adjust"]', row).onclick = () => { row.remove(); $("#input").focus(); };
  last.querySelector(".bot-body").appendChild(row);
  scrollEnd();
}

// ── @arquivo ───────────────────────────────────────────────────────────────────
let mention = null, mentionSeq = 0;
async function mentionHint() {
  const i = $("#input"), upto = i.value.slice(0, i.selectionStart);
  const m = upto.match(/(^|\s)@("?)([^\s"@]*)$/);
  if (!m || !S.workspace_set) return closeMention();
  const seq = ++mentionSeq;
  const items = await call("searchFiles", m[3]) || [];
  if (seq !== mentionSeq || i.value.slice(0, i.selectionStart) !== upto) return;   // já digitou mais
  if (!items.length) return closeMention();
  mention = { start: upto.length - m[3].length - m[2].length - 1, end: upto.length, items, index: 0 };
  renderMention();
}
function renderMention() {
  const box = $("#mention-pop");
  box.innerHTML = `<div class="mp-head">${icon("at")} Arquivos do projeto <span>↑↓ escolher · Enter insere · Esc fecha</span></div>` +
    mention.items.map((p, k) => {
      const cut = p.lastIndexOf("/");
      return `<div class="mp-item ${k === mention.index ? "on" : ""}" data-k="${k}">${icon("file")}<b>${esc(p.slice(cut + 1))}</b><span>${esc(cut > 0 ? p.slice(0, cut) : "")}</span></div>`;
    }).join("");
  box.classList.add("on");
  $$(".mp-item", box).forEach(el => el.addEventListener("mousedown", e => { e.preventDefault(); pickMention(+el.dataset.k); }));
  const on = $(".mp-item.on", box); if (on) on.scrollIntoView({ block: "nearest" });
}
function closeMention() { mention = null; mentionSeq++; const box = $("#mention-pop"); if (box) box.classList.remove("on"); }
function pickMention(k) {
  const i = $("#input"), path = mention.items[k];
  const token = "@" + (/\s/.test(path) ? `"${path}"` : path) + " ";
  i.value = i.value.slice(0, mention.start) + token + i.value.slice(mention.end);
  const pos = mention.start + token.length;
  closeMention(); i.focus(); i.setSelectionRange(pos, pos); autosize();
}
function mentionKey(e) {
  if (!mention) return false;
  const n = mention.items.length;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { mention.index = (mention.index + (e.key === "ArrowDown" ? 1 : n - 1)) % n; renderMention(); }
  else if (e.key === "Enter" || e.key === "Tab") pickMention(mention.index);
  else if (e.key === "Escape") closeMention();
  else return false;
  e.preventDefault(); e.stopPropagation();
  return true;
}

// ── Atualizações ───────────────────────────────────────────────────────────────
function onUpdate(e) {
  if (e.error) { S.updateError = e.error; if (settingsSection === "sobre") renderSettings(); return toast("error", "Atualizações", e.error); }
  S.update = e.info; S.updateError = "";
  if ($("#page-settings").classList.contains("active") && settingsSection === "sobre") renderSettings();
  const u = e.info;
  if (!u.available) return e.manual && toast("success", "Tudo em dia", "Você já está com a versão mais recente do Órbita.");
  const n = u.count || 0;
  toast("update", "Atualização disponível", `${n} ${n === 1 ? "melhoria nova" : "melhorias novas"} no Órbita${u.significant ? "" : " (só documentação)"}.`, 0,
    { label: "Ver novidades", fn: () => updateModal(u) });
}
function updateStatusText() {
  const inst = S.install || {};
  const where = inst.mode === "git" ? `cópia git${inst.sha ? " · " + esc(inst.sha) : ""}` : `código baixado${inst.sha ? " · " + esc(inst.sha) : ""}`;
  if (S.updateError) return `<span style="color:var(--err)">${esc(S.updateError)}</span>`;
  if (!S.update) return `v${esc(S.version || "")} · ${where}. Ainda não verificado nesta sessão.`;
  return S.update.available ? `<span style="color:var(--warn)">● Há uma atualização disponível</span> · ${where}`
    : `<span style="color:var(--ok)">● Em dia</span> · v${esc(S.version || "")} · ${where}`;
}
function updateModal(u) {
  const f = u.files || {}, changed = (f.changed || []).length, added = (f.added || []).length, removed = f.removed || [];
  const version = u.remote_version && u.remote_version !== S.version ? `<span class="tag grad">v${esc(S.version)} → v${esc(u.remote_version)}</span>` : "";
  const groups = Object.entries(u.groups || {}).map(([g, items]) => `<div class="up-group"><b>${esc(g)}</b><ul>${items.slice(0, 6).map(t => `<li>${esc(t)}</li>`).join("")}${items.length > 6 ? `<li class="more">e mais ${items.length - 6}…</li>` : ""}</ul></div>`).join("");
  const files = u.mode === "git"
    ? `<li>Atualiza pelo <b>git</b> (<code>git pull</code>), do jeito que você clonou.</li>`
    : `<li><b>${changed}</b> ${changed === 1 ? "arquivo do programa atualizado" : "arquivos do programa atualizados"}${added ? `, <b>${added}</b> ${added === 1 ? "novo" : "novos"}` : ""}.</li>
       ${removed.length ? `<li><b>Serão removidos</b> (não existem mais no programa): ${removed.slice(0, 8).map(p => `<code>${esc(p)}</code>`).join(", ")}${removed.length > 8 ? "…" : ""}</li>` : "<li>Nenhum arquivo será apagado.</li>"}
       <li>Antes de substituir ou remover, o Órbita guarda uma cópia em <code>data/updates/backup-…</code>.</li>`;
  openModal(`<div class="modal update-modal">
    <div class="up-head"><img src="logo.svg" alt=""><div><h2>Atualização do Órbita</h2><p class="sub">Melhorias publicadas no GitHub ${version}</p></div></div>
    <div class="up-groups">${groups || `<p class="sub">Ajustes gerais no programa.</p>`}</div>
    <div class="up-safe"><b>${icon("shield")} Seus arquivos</b><ul>
      <li>Ficam intactos: conversas, configurações, perfis, chaves (<code>.env</code>), memória, modelos e o ambiente Python.</li>${files}
      <li>O Órbita fecha, atualiza e abre de novo sozinho, em alguns segundos.</li></ul></div>
    ${u.blocked ? `<div class="up-blocked">${icon("alert")} ${esc(u.blocked)}</div>` : ""}
    ${!u.blocked && (u.local_changes || []).length ? `<div class="up-blocked up-local">${icon("info")} Você alterou ${u.local_changes.length === 1 ? "um arquivo" : u.local_changes.length + " arquivos"} do programa (${esc(u.local_changes.slice(0, 4).join(", "))}${u.local_changes.length > 4 ? "…" : ""}). A atualização guarda essas alterações, atualiza e as reaplica por cima. Uma cópia fica em data/updates/backup-…; se alguma conflitar com a versão nova, fica a nova e a sua continua na cópia.</div>` : ""}
    <div class="actions"><button class="btn" id="up-gh">${icon("globe")} Ver no GitHub</button><button class="btn" id="up-later">Depois</button>
      <button class="btn primary" id="up-go" ${u.blocked ? "disabled" : ""}>${icon("download")} ${(u.local_changes || []).length ? "Atualizar guardando minhas alterações" : "Atualizar agora"}</button></div></div>`);
  $("#up-gh").onclick = () => call("openUrl", u.url);
  $("#up-later").onclick = closeModal;
  $("#up-go").onclick = async () => {
    if (busy) return toast("warn", "Aguarde", "Espere o agente terminar a tarefa atual.");
    $("#up-go").disabled = true; $("#up-go").innerHTML = `<span class="spin"></span> Atualizando…`;
    const r = await call("applyUpdate", u.remote, (u.local_changes || []).length > 0);
    if (r && r.error) { toast("error", "Atualização", r.error); closeModal(); }
  };
}

// ── Pontos de restauração ──────────────────────────────────────────────────────
function checkpointCard(e) {
  const last = $$(".msg.bot").pop();
  if (!last) return;
  const files = e.changes || [];
  const add = files.reduce((s, c) => s + (c.added || 0), 0), del = files.reduce((s, c) => s + (c.removed || 0), 0);
  const kind = { A: "novo", M: "alterado", D: "apagado" };
  const el = document.createElement("div"); el.className = "cp-card";
  el.innerHTML = `<div class="cp-head">${icon("diff")}<b>${files.length} ${files.length === 1 ? "arquivo alterado" : "arquivos alterados"}</b><span class="cp-stat"><i class="add">+${add}</i><i class="del">−${del}</i></span><span class="grow"></span>
    <button class="btn small" data-cp="diff">${icon("eye")} Ver alterações</button><button class="btn small" data-cp="undo">${icon("undo")} Desfazer</button></div>
    <div class="cp-files">${files.slice(0, 8).map(c => `<span class="cp-f ${esc(c.status)}" title="${kind[c.status] || c.status}"><i>${esc(c.status)}</i>${esc(c.path)}</span>`).join("")}${files.length > 8 ? `<span class="cp-more">+${files.length - 8}</span>` : ""}</div>`;
  const ref = { workspace: e.workspace, before: e.before, after: e.after };
  $('[data-cp="diff"]', el).onclick = () => showDiff(ref);
  $('[data-cp="undo"]', el).onclick = () => undoCheckpoint(el, ref, false);
  last.querySelector(".bot-body").appendChild(el);
  feed("ok", `✓ ${files.length} ${files.length === 1 ? "arquivo alterado" : "arquivos alterados"} · ponto de restauração salvo`);
  scrollEnd();
}
async function showDiff(ref) {
  const r = await call("checkpointDiff", JSON.stringify(ref));
  if (!r || r.error) return toast("error", "Alterações", r ? r.error : "Falhou.");
  const meta = /^(\+\+\+|---|index |new file|deleted file|similarity|Binary files)/;
  const lines = r.diff.split("\n").map(l => {
    const cls = l.startsWith("diff --git") ? "f" : meta.test(l) ? "m" : l.startsWith("@@") ? "h" : l[0] === "+" ? "a" : l[0] === "-" ? "d" : "";
    return `<span class="${cls}">${esc(l.startsWith("diff --git") ? l.replace(/^diff --git a\/(.*) b\/.*$/, "$1") : l) || " "}</span>`;
  }).join("");   // cada linha já é um bloco: "\n" entre elas dobraria o espaçamento
  openModal(`<div class="modal diff-modal"><div class="dm-head"><b>${icon("diff")} O que esta resposta mudou</b><button class="icon-btn" id="dm-x">${icon("x")}</button></div><pre class="diff">${lines}</pre></div>`);
  $("#dm-x").onclick = closeModal;
}
async function undoCheckpoint(el, ref, redo) {
  if (busy) return toast("warn", "Aguarde", "Espere o agente terminar.");
  if (!redo && !(await confirmBox("Desfazer estas alterações?", "Os arquivos voltam a ser como eram antes desta resposta. O estado atual fica guardado, então dá para refazer.", "Desfazer"))) return;
  const r = await call("checkpointUndo", JSON.stringify(ref));
  if (!r || r.error) return toast("error", redo ? "Refazer" : "Desfazer", r ? r.error : "Falhou.");
  const n = r.restored.length + r.removed.length;
  toast("success", redo ? "Refeito" : "Desfeito", `${n} ${n === 1 ? "arquivo voltou" : "arquivos voltaram"} ${redo ? "à versão do agente" : "ao que eram antes"}.`);
  undoNote = redo ? "" : "\n\n(Obs.: desfiz pelo Órbita as alterações de arquivos da sua resposta anterior.)";
  el.classList.toggle("undone", !redo);
  const btn = $('[data-cp="undo"]', el);
  if (!r.redo) return btn.remove();
  const next = { workspace: ref.workspace, before: r.redo[0], after: r.redo[1] };
  btn.innerHTML = redo ? `${icon("undo")} Desfazer` : `${icon("redo")} Refazer`;
  btn.onclick = () => undoCheckpoint(el, next, !redo);
}
function ensureTurn(model) {
  if (turnEl) return turnEl;
  const el = document.createElement("div");
  el.className = "msg bot";
  el.innerHTML = `<div class="bot-avatar"><img src="logo.svg" alt=""></div><div class="bot-body">
    <div class="bot-meta"><b>${esc(S.profile?.name || "Agente")}</b><span class="model">${esc(model || S.model_label || "")}</span></div><div class="flow"></div></div>`;
  $("#messages").appendChild(el);
  turnEl = el; stepsBox = null;
  return el;
}
function closeTurn() {
  endThought();
  if (stepsBox) finishSteps(stepsBox);
  $$(".cursor", turnEl || document).forEach(c => c.classList.remove("cursor"));
  turnEl = null; stepsBox = null;
}
function flow() { return ensureTurn().querySelector(".flow"); }
function segment(id, html, streaming) {
  let el = segEls[id];
  if (!el) {
    if (stepsBox) { finishSteps(stepsBox); stepsBox = null; }
    el = document.createElement("div"); el.className = "prose"; segEls[id] = el; flow().appendChild(el);
  }
  el.innerHTML = html;
  el.classList.toggle("cursor", !!streaming);
  scrollEnd();
}
// ── Componente de Pensamento expansível ───────────────────────────────────────
// Bloco de raciocínio: aberto enquanto o modelo pensa (texto completo, rolagem própria);
// quando ele passa a escrever ou usar ferramenta, vira "Raciocínio · Xs", fechado e expansível.
let thoughtEl = null;
function thought(text) {
  let el = thoughtEl && thoughtEl.isConnected && !thoughtEl.classList.contains("done") ? thoughtEl : null;
  if (!el) {
    if (stepsBox) { finishSteps(stepsBox); stepsBox = null; }
    el = document.createElement("details");
    el.className = "thought"; el.open = true; el.dataset.start = Date.now();
    el.innerHTML = `<summary><span class="thought-label">${icon("brain")}<span class="tl">Pensando…</span><span class="thought-status">0s</span></span><span class="thought-action">${icon("chevright")}</span></summary>
      <div class="thought-content"></div>
      <div class="thought-toolbar"><span class="meta"></span><button class="icon-btn" title="Copiar o raciocínio">${icon("clip")}</button></div>`;
    $(".thought-toolbar button", el).onclick = e => {
      e.preventDefault(); call("copyText", $(".thought-content", el).textContent);
      toast("success", "Copiado", "Raciocínio copiado.", 1600);
    };
    flow().appendChild(el);
    thoughtEl = el;
  }
  const box = $(".thought-content", el);
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.textContent = text;
  if (atBottom) box.scrollTop = box.scrollHeight;   // acompanha o stream, a menos que a pessoa tenha rolado para ler
  $(".thought-status", el).textContent = Math.round((Date.now() - el.dataset.start) / 1000) + "s";
  scrollEnd();
}
function endThought() {
  const el = thoughtEl;
  if (!el || el.classList.contains("done")) return;
  const secs = Math.max(1, Math.round((Date.now() - el.dataset.start) / 1000));
  const words = ($(".thought-content", el).textContent.match(/\S+/g) || []).length;
  el.classList.add("done"); el.open = false;
  $(".tl", el).textContent = "Raciocínio";
  $(".thought-status", el).textContent = `${secs}s`;
  $(".thought-toolbar .meta", el).textContent = `${words} palavras · ${secs}s pensando`;
  thoughtEl = null;
}
const TOOL_INFO = {
  read_file: ["file", "Lendo arquivo"], write_file: ["edit2", "Escrevendo arquivo"], edit_file: ["edit", "Editando arquivo"],
  list_dir: ["folder", "Listando pasta"], glob_files: ["search", "Procurando arquivos"], grep: ["search", "Buscando no conteúdo"],
  run_shell: ["term", "Executando comando"], web_search: ["globe", "Pesquisando na web"], fetch_url: ["globe", "Lendo página"],
  open_app: ["bolt", "Abrindo programa"], screenshot: ["eye", "Olhando a tela"], mouse_click: ["mouse", "Clicando"],
  mouse_scroll: ["mouse", "Rolando"], type_text: ["term", "Digitando"], press_keys: ["term", "Pressionando teclas"],
  clipboard: ["clip", "Área de transferência"], system_info: ["cpu", "Status do sistema"], list_processes: ["cpu", "Listando processos"],
  close_app: ["x", "Fechando programa"], set_volume: ["wave", "Ajustando volume"], remember: ["brain", "Memorizando"],
  recall: ["brain", "Lembrando"], use_skill: ["book", "Carregando skill"], delegate_task: ["users", "Delegando à equipe"],
  find_tools: ["plug", "Buscando ferramentas"], generate_image: ["image", "Gerando imagem"], show_file: ["eye", "Mostrando arquivo"],
  toolbox_install: ["download", "Instalar programa de criação"], toolbox_list: ["layers", "Ferramentas de criação"],
  check_web_page: ["globe", "Testando página"],
};
function toolInfo(name) {
  if (name.startsWith("mcp__")) { const [, srv, tool] = name.split("__"); return ["plug", `${srv} › ${(tool || "").replace(/_/g, " ")}`]; }
  return TOOL_INFO[name] || ["sparkle", name];
}
function toolStep(d) {
  let el = stepEls[d.id];
  if (!el) {
    if (!stepsBox) {
      stepsBox = document.createElement("details");
      stepsBox.className = "steps"; stepsBox.open = true;
      stepsBox.innerHTML = `<summary>${icon("chevright", "i chev")}<span class="sum">Trabalhando…</span></summary><div class="list"></div>`;
      flow().appendChild(stepsBox);
    }
    const [ic, label] = toolInfo(d.name);
    el = document.createElement("div"); el.className = "step";
    el.innerHTML = `<span class="ic">${icon(ic)}</span><div class="lbl">${d.agent && d.agent !== "principal" ? `<span class="who">${esc(d.agent)}</span>` : ""}<b>${esc(label)}</b><span class="arg">${esc(d.summary || "")}</span></div><span class="st"><span class="spin"></span></span>`;
    stepsBox.querySelector(".list").appendChild(el);
    stepEls[d.id] = el;
    updateStepsSummary(stepsBox);
  }
  if (d.status && d.status !== "running") {
    const st = el.querySelector(".st");
    st.className = "st " + d.status;
    st.innerHTML = icon(d.status === "ok" ? "check" : "alert");
    if (d.result || (d.images || []).length) {
      const det = document.createElement("details");
      det.innerHTML = `<summary>ver resultado</summary><pre>${esc(d.result || "")}</pre>${(d.images || []).map(p => `<img class="zoomable" src="${fileUrl(p)}">`).join("")}`;
      if ((d.images || []).length) det.open = true;
      el.appendChild(det);
    }
    updateStepsSummary(el.closest(".steps"));
  }
  scrollEnd();
}
function updateStepsSummary(box) {
  if (!box) return;
  const all = $$(".step", box).length, done = $$(".st.ok, .st.error", box).length, errs = $$(".st.error", box).length;
  box.querySelector(".sum").textContent = done < all ? `Trabalhando… ${done}/${all} ações` : `${all} ${all === 1 ? "ação" : "ações"}${errs ? ` · ${errs} com erro` : ""}`;
}
function finishSteps(box) { updateStepsSummary(box); if (!$$(".st.error", box).length && $$(".step", box).length > 2) box.open = false; }
function subCard(d, done) {
  const id = "sub-" + d.agent;
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement("div"); el.className = "sub-card"; el.id = id; flow().appendChild(el);
  }
  el.innerHTML = `${done ? icon("check") : `<span class="spin"></span>`}<span class="nm">${esc(d.agent)}</span><span class="mdl">${esc(d.model || "")}</span><span class="tsk">${esc(done ? `concluído · ${fmt(d.tokens)} tokens` : d.task || "")}</span>`;
  scrollEnd();
}
function note(text, cls = "") {
  const el = document.createElement("div"); el.className = "note " + cls; el.textContent = text;
  $("#messages").appendChild(el); scrollEnd();
}
function scrollEnd(force) {
  const m = $("#messages");
  if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 160) m.scrollTop = m.scrollHeight;
}

// ── Anexos ─────────────────────────────────────────────────────────────────────
function addAttachments(paths) {
  const imgs = paths.filter(p => /\.(png|jpe?g|gif|webp|bmp)$/i.test(p));
  const others = paths.filter(p => !imgs.includes(p));
  attachments.push(...imgs);
  if (others.length) { const i = $("#input"); i.value += (i.value ? " " : "") + others.join(" "); autosize(); }
  renderAttachments();
}
function renderAttachments() {
  $("#attachments").innerHTML = attachments.map((p, i) => `<div class="att"><img src="${fileUrl(p)}"><span>${esc(p.split(/[\\/]/).pop())}</span><button data-rm="${i}">${icon("x")}</button></div>`).join("");
  $$("[data-rm]", $("#attachments")).forEach(b => b.addEventListener("click", () => { attachments.splice(+b.dataset.rm, 1); renderAttachments(); }));
}

// ── Ao vivo / equipe ───────────────────────────────────────────────────────────
function feed(kind, html, extra = {}) {
  const box = $("#feed");
  if ($(".empty", box)) box.innerHTML = "";
  
  // Tipos de eventos com seus estilos
  const kindStyles = {
    "ok": { icon: "check", color: "var(--ok)", label: "Sucesso" },
    "error": { icon: "alert", color: "var(--err)", label: "Erro" },
    "sub": { icon: "users", color: "var(--pink)", label: "Sub-agente" },
    "warning": { icon: "alert", color: "var(--warn)", label: "Aviso" },
    "info": { icon: "info", color: "var(--accent2)", label: "Info" },
    "thinking": { icon: "brain", color: "var(--accent)", label: "Pensando" },
    "tool": { icon: "plug", color: "var(--muted)", label: "Ferramenta" },
  };
  
  const style = kindStyles[kind] || kindStyles["info"];
  const tokens = extra.tokens ? ` • ${fmt(extra.tokens)} tokens` : "";
  const duration = extra.duration ? ` • ${extra.duration}ms` : "";
  
  const el = document.createElement("div"); 
  el.className = "feed-item " + kind;
  el.innerHTML = `<i class="b" style="background:${style.color}"></i><div>
    <div class="tm">${now()}${duration}</div>
    <div class="tx"><span class="feed-label">${style.label}</span><span class="feed-status">${html}</span></div>
  </div>`;
  
  // Permitir expandir detalhes se houver
  if (extra.details) {
    const details = document.createElement("details");
    details.className = "feed-details";
    details.innerHTML = `<summary class="sub">Ver detalhes</summary><pre class="feed-pre">${esc(extra.details)}</pre>`;
    el.querySelector(".tx").appendChild(details);
  }
  
  box.prepend(el);
  while (box.children.length > 300) box.lastChild.remove();
}
function renderAgents(live = {}) {
  const team = S.team || [];
  $("#agents").innerHTML = team.map(m => `<div class="agent-row">${agentIcon(m, 30)}<div class="grow"><b>${esc(m.name)}</b><div class="sm">${esc(m.model_label)}</div></div>${live[m.name] ? `<span class="spin"></span>` : ""}</div>`).join("")
    + `<button class="btn small" data-go="team">${icon("edit")} Configurar equipe</button>`;
}
function setLive(on, text) {
  const el = $("#live");
  if (on) {
    if (!el.classList.contains("on")) { liveStart = Date.now(); clearInterval(liveTimer); liveTimer = setInterval(() => { $("#live-clock").textContent = Math.round((Date.now() - liveStart) / 1000) + "s"; }, 500); }
    el.classList.add("on");
    if (text) $("#live-text").textContent = text;
  } else { el.classList.remove("on"); clearInterval(liveTimer); }
}

// ── Eventos do Python ──────────────────────────────────────────────────────────
function onEvent(e) {
  switch (e.type) {
    case "busy":
      busy = e.busy;
      $("#send").classList.toggle("stop", busy);
      $("#send").innerHTML = icon(busy ? "stop" : "send");
      $("#send").title = busy ? "Parar (Esc)" : "Enviar";
      setLive(busy, busy ? "Pensando…" : "");
      if (!busy) { closeTurn(); $("#mic").classList.remove("rec"); if (pendingApproval) closeModal(); }
      break;
    case "turn_start": closeTurn(); ensureTurn(e.model); break;
    case "seg": segment(e.id, e.html, e.streaming); break;
    case "reasoning": thought(e.text); setLive(true, "Raciocinando…"); break;
    case "reasoning_end": endThought(); if (busy) setLive(true, "Escrevendo…"); break;
    case "compact_done":
      if (e.ok) { note(`Conversa compactada: ${e.messages} mensagens viraram um resumo estruturado. O último pedido ficou intacto.`, "tip"); toast("success", "Conversa compactada", "Contexto liberado; o trabalho continua de onde parou."); }
      else toast("warn", "Compactar", e.error || "Não deu para compactar agora.", 7000);
      break;
    case "tool":
      toolStep(e);
      if (e.status === "running") { setLive(true, `${toolInfo(e.name)[1]}${e.summary ? " · " + e.summary : ""}`); feed("", `<b>${esc(e.agent || "principal")}</b> → ${esc(toolInfo(e.name)[1])} <span>${esc(e.summary || "")}</span>`); }
      else feed(e.status, `${e.status === "ok" ? "✓" : "✗"} ${esc(toolInfo(e.name)[1])}`);
      if ((e.images || []).length) preview({ path: e.images[0], kind: "image" });
      break;
    case "sub_start": subCard(e, false); feed("sub", `<b>${esc(e.agent)}</b> começou com <b>${esc(e.model)}</b>`); renderAgents({ [e.agent.replace(/ #\d+$/, "")]: true }); break;
    case "sub_end": subCard(e, true); feed("ok", `✓ <b>${esc(e.agent)}</b> terminou (${fmt(e.tokens)} tokens)`); renderAgents(); break;
    case "status": setLive(true, e.text); break;
    case "usage": S.conversation_tokens = e.total; updateMeter(e.total); break;
    case "checkpoint": checkpointCard(e); break;
    case "update": onUpdate(e); break;
    case "updated":
      if (e.result.ok) {
        toast("success", "Órbita atualizado", `${(e.result.replaced || []).length + (e.result.added || []).length} arquivos do programa atualizados. Seus dados ficaram intactos.`
          + ((e.result.kept_local || []).length ? ` Suas alterações foram reaplicadas: ${e.result.kept_local.join(", ")}.` : ""), 9000);
        if ((e.result.conflicts || []).length) toast("warn", "Alterações suas em conflito", `Em ${e.result.conflicts.join(", ")} ficou a versão nova; a sua está em ${e.result.backup}.`, 0);
      }
      else toast("error", "A atualização não foi aplicada", e.result.error || "Erro desconhecido. Nada foi alterado.", 0);
      break;
    case "turn_end": closeTurn(); if (e.plan) planActions(); refreshConvs().then(() => { S.conversation_id = e.conversation_id || S.conversation_id; S.conversation_title = e.title || S.conversation_title; renderTopbar(); renderConvs(); }); break;
    case "error": note("⚠ " + e.message, "err"); toast("error", "Erro", e.message); break;
    case "compacted": note(`Histórico compactado: ${e.messages} mensagens antigas viraram um resumo`); break;
    case "approval": approval(e); break;
    case "preview": preview(e); break;
    case "toast": toast(e.kind, e.title, e.text, e.ms || 4200); break;
    case "voice_text": if ($(".welcome")) $("#messages").innerHTML = ""; addUser(e.text); break;
    case "listening": $("#mic").classList.add("rec"); setLive(true, "Ouvindo…"); break;
    case "dictation": onDictation(e); break;
    case "toolbox": onToolbox(e); break;
    case "voice_gpu":
      if (e.state === "done") { toast("success", "Ditado", "Pronto: o ditado agora usa a placa de vídeo."); renderVoiceGpu({ cuda: true, libs: true }); }
      else if (e.state === "error") { toast("error", "Placa de vídeo", "A instalação falhou: " + (e.message || ""), 10000); renderVoiceGpu({ cuda: true, libs: false }); }
      break;
    case "mcp": S.mcp = e.servers; $("#mcp-dot").classList.toggle("on", e.servers.some(s => s.status === "erro")); if ($("#page-connections").classList.contains("active")) renderConnections(); break;
    case "state": S = { ...S, ...e.state }; renderAll(); break;
    case "models": onModels(e); break;
    case "probe": onProbe(e); break;
    case "pull": onPull(e); break;
  }
}

// ── Pré-visualização ───────────────────────────────────────────────────────────
function preview(e) {
  const box = $("#preview");
  box.innerHTML = `<div class="path">${esc(e.path)}</div>` + (e.kind === "image"
    ? `<img class="zoomable" src="${fileUrl(e.path)}">`
    : `<div class="prose">${e.html || ""}</div>`) + `<div class="row" style="margin-top:10px"><button class="btn small" id="pv-open">${icon("eye")} Abrir</button><button class="btn small" id="pv-folder">${icon("folder")} Mostrar na pasta</button></div>`;
  $("#pv-open").onclick = () => call("openPath", e.path);
  $("#pv-folder").onclick = () => call("revealPath", e.path);
  selectTab("preview");
}
function lightbox(src) { openModal(`<div class="lightbox"><img src="${src}"></div>`, true); }

// ── Notificações ───────────────────────────────────────────────────────────────
function toast(kind = "info", title = "", text = "", ms = 4200, act = null) {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  const ic = { success: "check", error: "alert", warn: "alert", info: "info", update: "download" }[kind] || "sparkle";
  el.innerHTML = `<div class="ti">${icon(ic)}</div><div><b>${esc(title)}</b><span>${esc(text)}</span>${act ? `<button class="btn primary small t-act">${esc(act.label)}</button>` : ""}</div><button class="close">${icon("x")}</button>${ms ? `<i class="life" style="animation-duration:${ms}ms"></i>` : ""}`;
  const kill = () => { el.classList.add("out"); setTimeout(() => el.remove(), 260); };
  el.querySelector(".close").onclick = kill;
  if (act) el.querySelector(".t-act").onclick = () => { kill(); act.fn(); };
  $("#toasts").appendChild(el);
  if (ms) setTimeout(kill, ms);   // ms = 0: fica até a pessoa fechar
  while ($("#toasts").children.length > 4) $("#toasts").firstChild.remove();
}

// ── Modais ─────────────────────────────────────────────────────────────────────
function openModal(html, clickClose = true) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="backdrop">${html}</div>`;
  hydrateIcons(root);
  if (clickClose) root.querySelector(".backdrop").addEventListener("mousedown", e => { if (e.target.classList.contains("backdrop")) closeModal(); });
  const first = root.querySelector("input, textarea, button.primary");
  if (first) setTimeout(() => first.focus(), 30);
}
let pendingApproval = null;   // id da confirmação aberta: fechar sem responder conta como "não"
function closeModal() {
  if (pendingApproval) { call("answerApproval", pendingApproval, "no"); pendingApproval = null; }
  $("#modal-root").innerHTML = "";
}
function confirmBox(title, text, ok = "Confirmar") {
  return new Promise(resolve => {
    openModal(`<div class="modal"><h2>${esc(title)}</h2><p class="sub">${esc(text)}</p><div class="actions"><button class="btn" id="cf-no">Cancelar</button><button class="btn primary" id="cf-ok">${esc(ok)}</button></div></div>`);
    $("#cf-no").onclick = () => { closeModal(); resolve(false); };
    $("#cf-ok").onclick = () => { closeModal(); resolve(true); };
  });
}
function approval(e) {
  const r = e.request;
  let body;
  if (r.type === "budget") {
    body = `<h2>Limite de tokens</h2><p class="sub">${esc(r.message)}</p>
      <div class="actions"><button class="btn" data-a="no">Parar aqui</button><button class="btn" data-a="always">Continuar sem perguntar</button><button class="btn primary" data-a="yes">Continuar</button></div>`;
  } else {
    const [ic, label] = toolInfo(r.tool);
    const args = r.args || {};
    const main = r.detail || args.command || args.path || args.name || args.text || args.url || "";
    body = `<div class="row" style="margin-bottom:10px"><span class="risk ${r.risk}">${icon("shield")} ${r.risk === "exec" ? "Executar / controlar o PC" : "Alterar arquivos"}</span><span class="tag">${esc(r.agent)}</span></div>
      <h2>${icon(ic)} ${esc(label)}</h2><p class="sub">O agente quer usar <b>${esc(r.tool)}</b>.</p>
      ${main ? `<pre>${esc(String(main)).slice(0, 2000)}</pre>` : ""}
      <details><summary class="sub" style="cursor:pointer">Todos os parâmetros</summary><pre>${esc(JSON.stringify(args, null, 2)).slice(0, 6000)}</pre></details>
      <div class="actions"><button class="btn danger" data-a="no">Negar</button><button class="btn" data-a="always">Permitir sempre nesta conversa</button><button class="btn primary" data-a="yes">Permitir</button></div>`;
  }
  closeModal();
  openModal(`<div class="modal">${body}</div>`, false);
  pendingApproval = e.id;
  $$("[data-a]", $("#modal-root")).forEach(b => b.addEventListener("click", () => { pendingApproval = null; call("answerApproval", e.id, b.dataset.a); closeModal(); }));
}

// ── Paleta de comandos ─────────────────────────────────────────────────────────
function palette(initial = "") {
  const cmds = [
    ["plus", "Nova conversa", () => action("new"), "Ctrl+N"],
    ["edit", "Renomear conversa", () => renameCurrentConv()],
    ["pin", "Prompt da conversa", () => pinnedPromptModal()],
    ["folder", "Abrir ou criar projeto", () => projectDialog()],
    ["globe", "Adicionar API manual", () => { settingsSection = "api"; go("settings"); }],
    ["settings", "Abrir configurações", () => go("settings"), "Ctrl+,"],
    ["cpu", "Trocar modelo", () => { settingsSection = "modelos"; go("settings"); }],
    ["users", "Equipe e perfis", () => go("team")],
    ["plug", "Conexões MCP e skills", () => go("connections")],
    ["panel", "Mostrar/ocultar painel ao vivo", () => action("toggle-side"), "Ctrl+B"],
    ["mic", "Ditar mensagem (fala vira texto)", () => toggleDictation(), "Ctrl+M"],
    ["wave", "Conversa por voz (fala e ouve a resposta)", () => action("voice")],
    ["layers", "Compactar conversa (resume o histórico)", () => compactConversation()],
    ["shield", "Alternar permissões", () => cyclePermission()],
    ["moon", "Alternar tema claro/escuro", () => action("theme")],
    ["key", "Chaves de API", () => { settingsSection = "chaves"; go("settings"); }],
    ["bolt", "Conta Grok (xAI)", () => { settingsSection = "grok"; go("settings"); }],
    ...(S.profiles || []).map(p => [null, `Perfil: ${p.name}`, async () => { S = await call("selectProfile", p.id); renderAll(); toast("success", "Perfil ativo", p.name); }]),
    ...(S.quick_prompts || []).map(q => ["sparkle", `Prompt: ${q.label}`, () => { $("#input").value = q.text; autosize(); $("#input").focus(); }]),
  ];
  openModal(`<div class="modal palette"><input id="pl-q" placeholder="Digite um comando…" value="${esc(initial)}"><div class="opts">${
    cmds.map((c, i) => `<div class="opt" data-i="${i}">${c[0] ? icon(c[0]) : ""}<span>${esc(c[1])}</span>${c[3] ? `<kbd>${c[3]}</kbd>` : ""}</div>`).join("")}</div></div>`);
  $$(".opt", $("#modal-root")).forEach(o => o.addEventListener("click", () => { closeModal(); if ($("#input").value === "/") $("#input").value = ""; cmds[+o.dataset.i][2](); }));
  filterOpts("#pl-q");
}

// ── Compactação de sessão ──────────────────────────────────────────────────────
// O agente já compacta sozinho perto do limite (85%); o botão faz isso na hora, quando a pessoa quiser.
async function compactConversation() {
  if (busy) return toast("warn", "Aguarde", "Espere o agente terminar antes de compactar.");
  if (!(await confirmBox("Compactar a conversa?",
    "O histórico antigo vira um resumo estruturado (objetivo, o que foi feito, decisões, estado atual e próximos passos) e o último pedido fica inteiro. Libera contexto e deixa o agente mais rápido e barato. As mensagens continuam visíveis na tela.",
    "Compactar"))) return;
  const r = await call("compactConversation");   // o resultado chega pelo evento compact_done
  if (r && r.error) toast("warn", "Compactar", r.error);
}
function filterOpts(sel) {
  const input = $(sel);
  let idx = 0;
  const visible = () => $$(".opt", $("#modal-root")).filter(o => o.style.display !== "none");
  const mark = () => { visible().forEach((o, i) => o.classList.toggle("sel", i === idx)); };
  input.addEventListener("input", () => {
    const q = input.value.toLowerCase();
    $$(".opt", $("#modal-root")).forEach(o => o.style.display = o.textContent.toLowerCase().includes(q) ? "" : "none");
    idx = 0; mark();
  });
  input.addEventListener("keydown", e => {
    const v = visible();
    if (e.key === "ArrowDown") { idx = Math.min(idx + 1, v.length - 1); mark(); e.preventDefault(); }
    if (e.key === "ArrowUp") { idx = Math.max(idx - 1, 0); mark(); e.preventDefault(); }
    if (e.key === "Enter" && v[idx]) v[idx].click();
  });
  mark();
}

// ── Página: Equipe e perfis ────────────────────────────────────────────────────
function renderTeamPage() {
  const tile = p => `<div class="tile"><div class="top"><div class="em has-ic">${agentIcon(p, 44)}</div><div style="flex:1"><h3>${esc(p.name)}</h3>
    ${p.in_team ? `<span class="tag grad">equipe</span>` : ""}${p.id === S.profile.id ? `<span class="tag grad">ativo</span>` : ""}${p.auto_startup ? `<span class="tag">prompt inicial</span>` : ""}</div></div>
    <div class="desc">${esc(p.description || "Sem descrição")}</div>
    <div>${(p.skills_tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    <div class="foot"><span class="mono" title="${esc(p.model_label)}">${icon("cpu")} ${esc(p.model_label)}</span>
      <button class="btn small" data-edit="${esc(p.id)}">${icon("edit")} Editar</button>
      ${p.id !== S.profile.id ? `<button class="btn small" data-use="${esc(p.id)}">Usar</button>` : ""}</div></div>`;
  const team = S.profiles.filter(p => p.in_team), others = S.profiles.filter(p => !p.in_team);
  const mode = S.settings.team_model === "auto" ? "auto" : "principal";
  $("#team-body").innerHTML = `<h1>Equipe e perfis</h1><p class="lead">Peça no chat algo como <i>“divida em 3 agentes: um faz o HTML, outro o CSS e outro o JS”</i>. O agente principal cria os ajudantes, eles trabalham <b>ao mesmo tempo</b> na mesma pasta, cada um na sua parte, e no fim ele revisa e junta tudo.</p>
    <div class="team-mode"><div class="tm-head">${icon("cpu")}<b>Qual modelo a equipe usa</b></div>
      <div class="tm-opts">
        <button class="tm-opt ${mode === "principal" ? "on" : ""}" data-team-model="principal"><b>Mesmo modelo do principal</b><span>Recomendado. Cada ajudante é uma cópia do agente principal (${esc(S.model_label || "")}) com uma tarefa diferente. Perfil com modelo fixo continua usando o dele.</span></button>
        <button class="tm-opt ${mode === "auto" ? "on" : ""}" data-team-model="auto"><b>Automático por especialidade</b><span>O Órbita escolhe o modelo de cada ajudante pelo catálogo e pelo modo de economia. Pode usar modelos locais ou mais baratos.</span></button>
      </div>
      <div class="tm-par"><div><b>Ajudantes ao mesmo tempo</b><span>Automático: até 6 com modelos de ponta na nuvem, 4 nos demais e 2 com modelo local (todos dividem a mesma placa). Se o agente criar mais, os outros esperam na fila. Pedidos grandes recebem a sugestão de dividir sozinhos.</span></div>
        <div class="seg" id="tm-par">${[["0", "Automático"], ["2", "2"], ["4", "4"], ["6", "6"], ["8", "8"]].map(([v, l]) => `<button data-v="${v}" class="${String(S.settings.team_max_parallel || 0) === v ? "on" : ""}">${l}</button>`).join("")}</div></div></div>
    <div class="row" style="margin-bottom:18px"><button class="btn primary" data-edit="">${icon("plus")} Novo perfil</button></div>
    <h3 style="color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.08em">Equipe</h3><div class="grid">${team.map(tile).join("")}</div>
    <h3 style="color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.08em;margin-top:26px">Perfis principais</h3><div class="grid">${others.map(tile).join("")}</div>`;
  $$("[data-edit]", $("#team-body")).forEach(b => b.addEventListener("click", () => profileEditor(S.profiles.find(p => p.id === b.dataset.edit))));
  $$("[data-use]", $("#team-body")).forEach(b => b.addEventListener("click", async () => { S = await call("selectProfile", b.dataset.use); renderAll(); renderTeamPage(); toast("success", "Perfil ativo", S.profile.name); }));
  $$("#tm-par button", $("#team-body")).forEach(b => b.addEventListener("click", async () => {
    await setSetting("team_max_parallel", +b.dataset.v, true); renderTeamPage();
    toast("success", "Equipe", +b.dataset.v ? `Até ${b.dataset.v} ajudantes ao mesmo tempo.` : "Quantidade automática conforme o modelo.");
  }));
  $$("[data-team-model]", $("#team-body")).forEach(b => b.addEventListener("click", async () => {
    await setSetting("team_model", b.dataset.teamModel, true); renderTeamPage();
    toast("success", "Equipe", b.dataset.teamModel === "auto" ? "Cada ajudante usa o modelo escolhido pela especialidade." : "Os ajudantes usam o mesmo modelo do agente principal.");
  }));
}
function providerOptions(selected, allowEmpty) {
  return (allowEmpty ? `<option value="">(usar o modelo padrão)</option>` : "") + S.providers.map(p => `<option value="${esc(p.id)}" ${p.id === selected ? "selected" : ""}>${esc(p.label)}${p.has_credentials ? "" : " — sem acesso"}</option>`).join("");
}
let peModelList = null;
function profileEditor(p) {
  const isNew = !p;
  p = p || { id: "", name: "", icon: "bot", description: "", system_prompt: "", startup_prompt: "", auto_startup: false, provider: "", model: "", temperature: null, effort: "", workspace: "", tool_groups: S.all_groups, mcp_servers: [], max_steps: null, in_team: false, skills_tags: [], bound: false };
  const groupLabels = { arquivos: "Arquivos", shell: "Terminal", web: "Internet", pc: "Controle do PC", memoria: "Memória", skills: "Skills", agentes: "Equipe", mcp: "MCP", imagem: "Imagens" };
  openModal(`<div class="modal wide"><h2>${isNew ? "Novo perfil" : "Editar perfil"}</h2><p class="sub">O prompt de sistema entra em toda conversa; o prompt inicial é enviado sozinho ao abrir uma conversa.</p>
    <div class="row"><input type="hidden" id="pe-icon" value="${esc(agentIconKey(p.icon) || p.icon)}"><input class="inp" id="pe-name" style="flex:1" placeholder="Nome" value="${esc(p.name)}"></div>
    <div class="icon-pick" id="pe-icons" style="margin-top:10px">${Object.keys(AGENT_ICONS).map(k =>
      `<button type="button" data-icon="${k}" class="${(agentIconKey(p.icon) || "") === k ? "on" : ""}" title="${esc(AGENT_ICONS[k].label)}">${agentIcon({ icon: k }, 34)}</button>`).join("")}</div>
    <div style="margin-top:10px"><input class="inp" id="pe-desc" placeholder="Descrição de uma linha (o agente principal lê isto para delegar)" value="${esc(p.description)}"></div>
    <div style="margin-top:12px"><b>Prompt de sistema (injeção)</b><textarea class="inp" id="pe-sys" placeholder="Ex.: Você é especialista em React + TypeScript…">${esc(p.system_prompt)}</textarea></div>
    <div style="margin-top:12px"><b>Prompt inicial</b><textarea class="inp" id="pe-start" style="min-height:70px" placeholder="Ex.: Leia o README do projeto e me diga o estado atual.">${esc(p.startup_prompt)}</textarea>
      <label class="row" style="margin-top:6px"><span class="toggle"><input type="checkbox" id="pe-auto" ${p.auto_startup ? "checked" : ""}><span></span></span> Enviar automaticamente ao abrir uma conversa</label></div>
    <div class="row" style="margin-top:14px"><div style="flex:1"><b>Provedor</b><select class="inp" id="pe-prov">${providerOptions(p.provider, true)}</select></div>
      <div style="flex:1"><b>Modelo</b><div class="row"><input class="inp" style="flex:1" id="pe-model" value="${esc(p.model)}" placeholder="nome do modelo" spellcheck="false" autocomplete="off"><button type="button" class="btn small" id="pe-refresh" title="Buscar modelos do provedor">${icon("refresh")}</button></div></div></div>
    <div class="warn-line" id="pe-warn"></div>
    <div id="pe-model-box">
      <label class="model-search">${icon("search")}<input id="pe-search" placeholder="Pesquisar modelo (ex.: claude son, qwen, gemini)…" spellcheck="false" autocomplete="off"><span class="cnt" id="pe-count">0 de 0</span></label>
      <div class="model-pick" id="pe-list"></div>
    </div>
    <label class="row" style="margin-top:8px"><span class="toggle"><input type="checkbox" id="pe-bind" ${p.bound ? "checked" : ""}><span></span></span> Ativar este perfil quando eu escolher este modelo</label>
    <div class="row" style="margin-top:12px"><div style="flex:2"><b>Pasta deste perfil</b><div class="row"><input class="inp" id="pe-ws" style="flex:1" value="${esc(p.workspace)}" placeholder="vazio = usar o projeto aberto na tela"><button class="btn small" id="pe-pick">${icon("folder")}</button></div></div>
      <div style="flex:1"><b>Temperatura</b><input class="inp" id="pe-temp" type="number" step="0.1" min="0" max="2" value="${p.temperature ?? ""}" placeholder="padrão"></div>
      <div style="flex:1"><b>Máx. passos</b><input class="inp" id="pe-steps" type="number" min="1" max="200" value="${p.max_steps ?? ""}" placeholder="padrão"></div></div>
    <div style="margin-top:12px"><b>Ferramentas liberadas</b><div class="row" style="margin-top:6px">${S.all_groups.map(g => `<label class="row" style="gap:6px;margin-right:10px"><input type="checkbox" class="pe-g" value="${g}" ${p.tool_groups.includes(g) ? "checked" : ""}> ${groupLabels[g] || g}</label>`).join("")}</div></div>
    <div class="row" style="margin-top:12px"><div style="flex:1"><b>Servidores MCP</b><input class="inp" id="pe-mcp" value="${esc(p.mcp_servers.join(", "))}" placeholder="vazio = todos"></div>
      <div style="flex:1"><b>Especialidades</b><input class="inp" id="pe-tags" value="${esc(p.skills_tags.join(", "))}" placeholder="código, testes…"></div></div>
    <label class="row" style="margin-top:10px"><span class="toggle"><input type="checkbox" id="pe-team" ${p.in_team ? "checked" : ""}><span></span></span> Faz parte da equipe (pode receber tarefas delegadas)</label>
    <div class="actions">${!isNew && p.id !== "geral" ? `<button class="btn danger" id="pe-del">${icon("trash")} Apagar</button>` : ""}<span style="flex:1"></span><button class="btn" id="pe-cancel">Cancelar</button><button class="btn primary" id="pe-save">Salvar perfil</button></div></div>`, false);
  peModelList = bindSearchableModels({
    provEl: $("#pe-prov"),
    modelEl: $("#pe-model"),
    searchEl: $("#pe-search"),
    countEl: $("#pe-count"),
    listEl: $("#pe-list"),
    warnEl: $("#pe-warn"),
    refreshBtn: $("#pe-refresh"),
    submitBtn: $("#pe-save"),
    boxEl: $("#pe-model-box"),
    isActive: (provId, m) => ($("#pe-model").value.trim() || S.model) === m,
    onPick: m => { $("#pe-model").value = m; peModelList(false); },
  });
  $$("[data-icon]", $("#pe-icons")).forEach(b => b.addEventListener("click", () => {
    $("#pe-icon").value = b.dataset.icon;
    $$("[data-icon]", $("#pe-icons")).forEach(x => x.classList.toggle("on", x === b));
  }));
  $("#pe-pick").onclick = async () => { const f = await call("pickFolder", $("#pe-ws").value); if (f) $("#pe-ws").value = f; };
  $("#pe-cancel").onclick = closeModal;
  if ($("#pe-del")) $("#pe-del").onclick = async () => { if (await confirmBox("Apagar perfil?", p.name)) { S = await call("deleteProfile", p.id); renderAll(); renderTeamPage(); } };
  $("#pe-save").onclick = async () => {
    const modelVal = $("#pe-prov").value ? $("#pe-model").value.trim() : "";
    if (looksLikeKey(modelVal)) return toast("error", "Isso é uma chave", "O campo Modelo está com uma chave de API. Escolha um modelo da lista.", 7000);
    const data = { id: p.id, name: $("#pe-name").value.trim(), icon: $("#pe-icon").value.trim() || "bot", description: $("#pe-desc").value.trim(),
      system_prompt: $("#pe-sys").value.trim(), startup_prompt: $("#pe-start").value.trim(), auto_startup: $("#pe-auto").checked,
      provider: $("#pe-prov").value, model: modelVal,
      temperature: $("#pe-temp").value === "" ? null : +$("#pe-temp").value, effort: p.effort || "", max_tokens: p.max_tokens ?? null,
      workspace: $("#pe-ws").value.trim(), tool_groups: $$(".pe-g").filter(c => c.checked).map(c => c.value),
      mcp_servers: $("#pe-mcp").value.split(",").map(s => s.trim()).filter(Boolean), max_steps: $("#pe-steps").value ? +$("#pe-steps").value : null,
      in_team: $("#pe-team").checked, skills_tags: $("#pe-tags").value.split(",").map(s => s.trim()).filter(Boolean), bind: $("#pe-bind").checked };
    if (!data.name) return toast("warn", "Perfil", "Dê um nome ao perfil.");
    const res = await call("saveProfile", JSON.stringify(data));
    if (res && res.error) return toast("error", "Perfil", res.error);
    S = res; closeModal(); renderAll(); renderTeamPage(); toast("success", "Perfil salvo", data.name);
  };
}

// ── Página: Conexões (MCP + skills) ────────────────────────────────────────────
const MCP_STATUS = { falta: "precisa instalar", indisponivel: "indisponível neste sistema" };
function renderConnections() {
  const servers = S.mcp || [];
  $("#conn-body").innerHTML = `<h1>Ferramentas de criação</h1><p class="lead">Programas que a IA sabe usar para editar imagens, modelar em 3D, fazer jogos e mexer em vídeo. Nada vem instalado: baixe só o que quiser (versão fixa, do site oficial, com conferência de integridade). O agente também pode pedir para instalar — sempre com a sua permissão.</p>
    <div class="grid" id="tb-grid"></div>
    <h1 style="margin-top:34px">Conexões</h1><p class="lead">Servidores MCP ligam o agente a programas (REA, navegador, Windows, Photoshop…). Servidores grandes carregam ferramentas sob demanda para economizar tokens.</p>
    <div class="row" style="margin-bottom:18px"><button class="btn" id="mc-reload">${icon("refresh")} Reconectar</button><button class="btn" id="mc-import">${icon("download")} Importar do Claude/Cursor</button><button class="btn" id="mc-edit">${icon("code")} Editar mcp.json</button></div>
    <div class="grid">${servers.map(s => `<div class="tile ${s.status === "indisponivel" ? "off" : ""}"><div class="top"><div class="em">${icon("plug")}</div><div style="flex:1"><h3>${esc(s.name)}</h3><span class="status ${s.status}"><i></i>${esc(MCP_STATUS[s.status] || s.status)}${s.status === "conectado" ? ` · ${s.tools} ferramentas${s.deferred ? " (sob demanda)" : ""}` : ""}</span></div>
      <label class="toggle"><input type="checkbox" data-mcp="${esc(s.name)}" ${s.enabled ? "checked" : ""} ${s.status === "indisponivel" ? "disabled" : ""}><span></span></label></div>
      <div class="desc">${esc(s.description || "")}${s.error ? `<div class="mcp-err ${s.status}">${esc(s.error)}</div>` : ""}</div></div>`).join("")}</div>
    <h1 style="margin-top:34px">Skills</h1><p class="lead">Instruções especializadas no padrão <b>SKILL.md</b>, lidas de <code>skills/</code>, plugins e das pastas do Claude/Codex.</p>
    <div class="grid">${(S.skills || []).map(k => `<div class="tile"><div class="top"><div class="em">${icon("book")}</div><div><h3>${esc(k.name)}</h3><span class="tag">${esc(k.origin)}</span></div></div><div class="desc">${esc(k.description)}</div></div>`).join("") || `<div class="empty">Nenhuma skill encontrada.</div>`}</div>`;
  $$("[data-mcp]", $("#conn-body")).forEach(t => t.addEventListener("change", () => { call("mcpToggle", t.dataset.mcp, t.checked); toast("info", "MCP", `${t.dataset.mcp} ${t.checked ? "ligando…" : "desligado"}`); }));
  $("#mc-reload").onclick = () => { call("mcpReload"); toast("info", "MCP", "Reconectando servidores…"); };
  $("#mc-import").onclick = async () => { const r = await call("mcpImport"); toast(r.length ? "success" : "info", "Importação MCP", r.length ? `Importados (desligados): ${r.join(", ")}` : "Nenhum servidor novo encontrado."); };
  $("#mc-edit").onclick = () => call("openPath", "mcp");
  renderToolbox();
}

// ── Caixa de ferramentas (programas opcionais) ─────────────────────────────────
const TB_ICONS = { imagemagick: "image", openscad: "layers", blender: "layers", godot: "bolt", ffmpeg: "wave" };
function renderToolbox() {
  const grid = $("#tb-grid");
  if (!grid) return;
  grid.innerHTML = (S.toolbox || []).map(t => {
    const busy = t.state === "downloading" || t.state === "extracting";
    const status = busy ? `<span class="status conectando"><i></i>${t.state === "extracting" ? "Extraindo…" : `Baixando ${t.pct || 0}%`}</span>`
      : t.installed ? `<span class="status conectado"><i></i>Instalado · v${esc(t.version)}</span>`
      : t.system_exe ? `<span class="status conectado"><i></i>Já está no sistema</span>`
      : t.available ? `<span class="status"><i></i>Não instalado · ${esc(t.size_label)}</span>`
      : `<span class="status"><i></i>Instale pelo sistema</span>`;
    const action = busy ? "" : t.installed ? `<button class="btn small danger" data-tb-remove="${esc(t.id)}">${icon("trash")} Remover</button>`
      : t.available && !t.system_exe ? `<button class="btn small primary" data-tb-install="${esc(t.id)}">${icon("download")} Instalar (${esc(t.size_label)})</button>` : "";
    const cmds = Object.entries(t.package_commands || {}).map(([k, v]) => `<code>${esc(v)}</code>`).join("<br>");
    return `<div class="tile tb-tile"><div class="top"><div class="em">${icon(TB_ICONS[t.id] || "plug")}</div><div style="flex:1"><h3>${esc(t.name)}</h3>${status}</div></div>
      <div class="desc">${esc(t.purpose)}</div>
      ${busy ? `<div class="progress"><i style="width:${t.state === "extracting" ? 100 : t.pct || 0}%"></i></div>` : ""}
      ${t.installed ? `<div class="tb-path" title="${esc(t.exe)}">${esc(t.test_line || t.exe)}</div>` : ""}
      ${!t.available && cmds ? `<div class="tb-path">${cmds}</div>` : ""}
      <div class="foot"><span class="mono">${t.source ? `de ${esc(t.source)}` : ""}</span>${action}</div></div>`;
  }).join("") || `<div class="empty">Catálogo vazio.</div>`;
  $$("[data-tb-install]", grid).forEach(b => b.addEventListener("click", async () => {
    const t = S.toolbox.find(x => x.id === b.dataset.tbInstall);
    if (!(await confirmBox(`Instalar ${t.name}?`, `Versão ${t.version} · ${t.size_label}, baixado de ${t.source} e conferido pelo SHA-256 antes de instalar. Fica em models/tools e pode ser removido quando quiser.`, "Baixar e instalar"))) return;
    call("toolboxInstall", t.id); onToolbox({ id: t.id, state: "downloading", pct: 0 });
  }));
  $$("[data-tb-remove]", grid).forEach(b => b.addEventListener("click", async () => {
    const t = S.toolbox.find(x => x.id === b.dataset.tbRemove);
    if (!(await confirmBox(`Remover ${t.name}?`, "O programa sai da caixa de ferramentas. Dá para instalar de novo depois.", "Remover"))) return;
    call("toolboxRemove", t.id);
  }));
}
async function onToolbox(e) {
  const t = (S.toolbox || []).find(x => x.id === e.id);
  if (!t) return;
  if (e.state === "downloading" || e.state === "extracting") { t.state = e.state; t.pct = e.pct; }
  else if (["done", "removed", "tested", "error"].includes(e.state)) {
    const fresh = await call("toolboxList");
    if (fresh) S.toolbox = fresh;
    const now = S.toolbox.find(x => x.id === e.id);
    if (e.state === "tested") { if (now) now.test_line = e.test; toast("success", t.name, `Instalado e testado: ${e.test}`, 7000); }
    if (e.state === "removed") toast("info", t.name, "Removido.");
    if (e.state === "error") toast("error", t.name, e.error || "A instalação falhou.", 9000);
  }
  if ($("#page-connections").classList.contains("active")) renderToolbox();
}

// ── Página: Configurações ──────────────────────────────────────────────────────
const SECTIONS = [
  ["geral", "user", "Geral"], ["modelos", "cpu", "Modelos"], ["api", "globe", "API manual"], ["chaves", "key", "Chaves de API"], ["grok", "bolt", "Conta Grok"],
  ["economia", "coins", "Economia de tokens"], ["permissoes", "shield", "Permissões"], ["voz", "wave", "Voz"], ["sobre", "info", "Sobre"],
];
function renderSettings() {
  $("#set-nav").innerHTML = `<h2>Configurações</h2>` + SECTIONS.map(([id, ic, label]) => `<div class="set-link ${id === settingsSection ? "active" : ""}" data-sec="${id}">${icon(ic)}${label}</div>`).join("");
  $$(".set-link").forEach(l => l.addEventListener("click", () => { settingsSection = l.dataset.sec; renderSettings(); }));
  const st = S.settings;
  const field = (label, help, control) => `<div class="field"><div class="l"><b>${label}</b><span>${help}</span></div><div>${control}</div></div>`;
  const toggle = (key, on) => `<label class="toggle"><input type="checkbox" data-set="${key}" ${on ? "checked" : ""}><span></span></label>`;
  const seg = (key, options, value) => `<div class="seg" data-seg="${key}">${options.map(([v, l]) => `<button data-v="${v}" class="${v === value ? "on" : ""}">${l}</button>`).join("")}</div>`;
  let html = "";
  switch (settingsSection) {
    case "geral":
      html = `<h1>Geral</h1><p class="lead">Quem você é e como o agente começa a trabalhar.</p><div class="group">
        ${field("Seu nome", "O agente usa para se dirigir a você.", `<input class="inp" data-text="user_name" value="${esc(st.user_name || "")}">`)}
        ${field("Projeto aberto", esc(S.workspace_set ? S.workspace : "Nenhuma pasta escolhida. O agente usa a sua pasta de usuário."), `<button class="btn primary" id="open-project">${icon("folder")} Abrir ou criar</button>`)}
        ${field("Tema", "Aparência da janela.", seg("theme", [["dark", "Escuro"], ["light", "Claro"]], st.theme || "dark"))}
        ${field("Notificações do Windows", "Avisa no canto da tela quando uma tarefa termina e a janela não está em foco.", toggle("native_notifications", st.native_notifications !== false))}
        ${field("Mostrar raciocínio", "Exibe o pensamento de modelos que raciocinam (DeepSeek-R1, Qwen3…).", toggle("show_reasoning", st.show_reasoning))}
        ${field("Assistente de primeira execução", "Refaça a configuração inicial guiada.", `<button class="btn small" id="re-onb">${icon("sparkle")} Abrir assistente</button>`)}
      </div>`; break;
    case "modelos":
      html = `<h1>Modelos</h1><p class="lead">Escolha a IA principal, gerencie os modelos locais e como a equipe escolhe modelos.</p>
        <div class="group"><h3>Modelo principal</h3>
        ${field("Provedor", "De onde vem a IA principal.", `<select class="inp" id="m-prov">${providerOptions(S.provider, false)}</select>`)}
        ${field("Modelo", "Clique em um modelo da lista abaixo ou digite o nome exato.", `<div class="row"><input class="inp" style="flex:1" id="m-model" value="${esc(S.model)}" placeholder="nome do modelo" spellcheck="false" autocomplete="off"><button class="btn small" id="m-refresh" title="Buscar modelos do provedor">${icon("refresh")}</button></div><div class="warn-line" id="m-warn"></div>`)}
        <label class="model-search">${icon("search")}<input id="m-search" placeholder="Pesquisar modelo (ex.: claude son, qwen 27b, gpt-4o)…" spellcheck="false" autocomplete="off"><span class="cnt" id="m-count">0 de 0</span></label>
        <div class="model-pick" id="m-list"></div>
        <div class="row" style="padding:10px 0"><button class="btn primary" id="m-apply">${icon("check")} Usar este modelo</button><span class="status" id="m-hint"></span></div></div>
        <div class="group"><h3>Modelos locais (Ollama)</h3><div id="local-models"><div class="empty">Carregando…</div></div>
        <div class="row" style="padding:12px 0"><input class="inp" style="flex:1" id="pull-name" placeholder="baixar modelo, ex.: qwen3:14b, llama3.2-vision, gemma3:12b"><button class="btn" id="pull-btn">${icon("download")} Baixar</button></div>
        <div id="pull-progress"></div>
        ${field("Contexto do Ollama", "Tokens de memória de trabalho (mais = mais VRAM).", `<input class="inp" type="number" step="2048" data-num="ollama_num_ctx" value="${st.ollama_num_ctx}">`)}
        ${field("Manter carregado", "Tempo que o modelo fica na VRAM entre mensagens (ex.: 10m, 1h, 0).", `<input class="inp" data-text="ollama_keep_alive" value="${esc(st.ollama_keep_alive)}">`)}</div>
        <div class="group"><h3>Equipe e modelos especiais</h3>
        ${field("Modelo da equipe", "Mesmo do principal: os ajudantes são cópias do agente principal. Automático: cada um usa o modelo da especialidade (pode ser local ou mais barato).", seg("team_model", [["principal", "Mesmo do principal"], ["auto", "Automático"]], st.team_model === "auto" ? "auto" : "principal"))}
        ${field("Modelo econômico", "Usado para resumos e quando o roteador não achar nada (provedor:modelo).", `<input class="inp" data-text="cheap_model" value="${esc(st.cheap_model || "")}" placeholder="ex.: deepseek:deepseek-chat">`)}
        ${field("Modelo de imagem", "Para gerar imagens; vazio = automático.", `<input class="inp" data-text="image_model" value="${esc(st.image_model || "")}" placeholder="ex.: openai:gpt-image-1">`)}
        ${field("Catálogo de capacidades", "Notas por especialidade e custo de cada modelo.", `<button class="btn small" id="cat-open">${icon("code")} Editar catálogo</button>`)}</div>
        <div class="group"><h3>Outra API</h3>
        <div class="row" style="padding:12px 0"><span style="color:var(--muted);flex:1">Together, Fireworks, Groq, um servidor seu ou LM Studio em outra porta.</span><button class="btn" id="goto-api">${icon("plus")} Adicionar API manual</button></div></div>`;
      break;
    case "api": {
      const custom = (S.providers || []).filter(p => !p.builtin);
      html = `<h1>API manual</h1><p class="lead">Cole o endereço de qualquer API compatível com a OpenAI. A chave fica só no <code>.env</code> deste computador. Servidor local pode ficar sem chave.</p>
        <div class="group">
        ${field("Nome", "Como ela aparece na lista. Ex.: Together, Fireworks, meu servidor.", `<input class="inp" id="api-name" placeholder="Together">`)}
        ${field("Endereço", "O link base. Quase sempre termina em /v1.", `<input class="inp" id="api-url" placeholder="https://api.together.xyz/v1" spellcheck="false">`)}
        ${field("Chave", "Opcional. Não é enviada para lugar nenhum além dessa API.", `<input class="inp" id="api-key" type="password" placeholder="cole a chave, se a API pedir" autocomplete="off">`)}
        ${field("Modelo", "O nome exato nessa API. Use Verificar para buscar a lista.", `<input class="inp" id="api-model" placeholder="ex.: meta-llama/Llama-3.3-70B-Instruct-Turbo" spellcheck="false">`)}
        <div class="row" style="padding:12px 0"><button class="btn" id="api-probe">${icon("refresh")} Verificar modelos</button><button class="btn primary" id="api-save">${icon("check")} Salvar e usar</button></div>
        <div class="status" id="probe-status"></div><div id="probe-models"></div></div>
        <div class="group"><h3>APIs que você adicionou</h3>
        ${custom.length ? custom.map(p => `<div class="api-row"><div class="who"><div class="nm">${esc(p.label)}</div><div class="sz">${esc(p.base_url || "")}${p.has_credentials ? "" : " · sem chave"}</div></div><button class="btn small" data-use-api="${esc(p.id)}">Usar</button><button class="btn small danger" data-drop-api="${esc(p.id)}">Remover</button></div>`).join("") : `<div class="empty">Nenhuma API extra ainda.</div>`}</div>`;
      break;
    }
    case "chaves":
      html = `<h1>Chaves de API</h1><p class="lead">Ficam somente no arquivo <code>.env</code> deste computador. Deixe em branco para manter a atual. Para um serviço que não está na lista, use <b>API manual</b>.</p><div class="group">
        ${S.providers.filter(p => p.api_key_env).map(p => field(esc(p.label), p.has_credentials ? `<span style="color:var(--ok)">● configurada</span> · ${esc(p.api_key_env)}` : esc(p.api_key_env),
          `<div class="row"><input class="inp" type="password" style="flex:1" data-key="${esc(p.api_key_env)}" placeholder="${p.has_credentials ? "••••••••  (manter)" : "cole a chave"}"><button class="btn small" data-savekey="${esc(p.api_key_env)}">Salvar</button></div>`)).join("")}</div>`;
      break;
    case "grok": {
      const g = S.grok || {};
      html = `<h1>Conta Grok (xAI)</h1><p class="lead">Use o agente <b>Grok Build</b> com a sua conta — o mesmo do Grok Build Desktop. O login abre o navegador; a sessão fica com o CLI oficial e se renova sozinha.</p>
        <div class="group">${field("Situação", "", `<span class="status ${g.logged_in ? "conectado" : g.installed ? "conectando" : "erro"}"><i></i>${g.logged_in ? "Conectado" : g.installed ? "Instalado, sem login" : "CLI não instalado"}</span><div class="sub" style="font-size:12px;color:var(--dim);margin-top:4px">${esc(g.version || "")}</div>`)}
        <div class="row" style="padding:14px 0"><button class="btn primary" data-grok="login">${icon("user")} Entrar (navegador)</button><button class="btn" data-grok="device">Entrar com código</button><button class="btn" data-grok="logout">Sair</button>${g.installed ? "" : `<button class="btn" data-grok="install">${icon("download")} Instalar CLI</button>`}<button class="btn small" data-grok="status">${icon("refresh")}</button></div></div>`;
      break;
    }
    case "economia": {
      const usage = S.usage || {};
      const max = Math.max(1, ...Object.values(usage).map(u => u.input + u.output));
      html = `<h1>Economia de tokens</h1><p class="lead">Produtividade sem gastar tudo de uma vez: o agente pausa e pergunta antes de passar dos limites.</p>
        <div class="group">${field("Modo", "Máximo: contexto enxuto e modelos baratos. Livre: mais contexto e os melhores modelos.", seg("economy_mode", [["maximo", "Máxima"], ["equilibrado", "Equilibrado"], ["livre", "Livre"]], st.economy_mode))}
        ${field("Orçamento por tarefa", "Tokens antes de pausar e perguntar (0 = sem limite).", `<input class="inp" type="number" step="50000" data-num="turn_token_budget" value="${st.turn_token_budget}">`)}
        ${field("Orçamento diário (nuvem)", "Modelos locais não contam (0 = sem limite).", `<input class="inp" type="number" step="100000" data-num="daily_token_budget" value="${st.daily_token_budget}">`)}</div>
        <div class="group"><h3>Uso de hoje</h3>${Object.entries(usage).map(([k, u]) => `<div class="usage-row"><span class="mono" style="font-family:var(--mono);font-size:12px">${esc(k)}</span><div class="bar"><i style="width:${(u.input + u.output) / max * 100}%"></i></div><span>${fmt(u.input + u.output)}</span></div>`).join("") || `<div class="empty">Nada usado hoje ainda.</div>`}</div>`;
      break;
    }
    case "permissoes":
      html = `<h1>Permissões</h1><p class="lead">Quanto o agente pode fazer sozinho.</p><div class="group">
        ${field("Modo", "Perguntar: confirma qualquer alteração. Automático: só comandos e controle do PC. Livre: nunca pergunta.", seg("permission_mode", [["perguntar", "Perguntar"], ["auto", "Automático"], ["livre", "Livre"]], st.permission_mode))}
        ${field("Pontos de restauração", "Antes de cada resposta o Órbita guarda uma foto da pasta do projeto (fora dela, sem tocar no seu git). Dá para ver o que mudou e desfazer com um clique.", toggle("checkpoints", st.checkpoints !== false))}</div>`;
      break;
    case "voz":
      html = `<h1>Voz</h1><p class="lead">Clique no microfone (ou Ctrl+M), fale e clique de novo: o texto aparece no campo enquanto você fala, e você revisa antes de enviar. Com chave da Groq ou da OpenAI, a transcrição vai para a nuvem (rápida em qualquer PC); sem chave, roda neste computador, sem internet.</p><div class="group">
        ${field("Onde transcrever", `<span id="stt-status">Verificando…</span>`, seg("stt_engine", [["auto", "Automático"], ["cloud", "Na nuvem"], ["local", "Neste PC"]], st.stt_engine || "auto"))}
        <div class="stt-tip">${icon("info")}<span><b>Na nuvem</b> é como no ChatGPT e no Claude: rápido em qualquer computador, mesmo fraco, porque o PC só grava e envia. Usa uma chave da <b>Groq</b> (tem plano grátis: <a href="https://console.groq.com/keys">console.groq.com/keys</a>) ou da <b>OpenAI</b>, colada em Chaves de API. <b>Neste PC</b> funciona sem internet e sem chave, com um modelo leve.</span></div>
        <h3 style="margin-top:18px">Opcional: transcrição neste PC</h3>
        ${field("Modelo local", "Leve (~150 MB, padrão) roda em qualquer PC. Melhor (~500 MB) e Máximo (~1,6 GB) são mais precisos e mais pesados: só valem a pena com placa de vídeo. O modelo é baixado só na primeira vez que for usado.", seg("stt_model", [["base", "Leve"], ["small", "Melhor"], ["large-v3-turbo", "Máximo"]], st.stt_model || "base"))}
        ${field("Placa de vídeo NVIDIA (opcional)", `<span id="vg-status">Verificando…</span>`, `<button class="btn small" id="vg-install" style="display:none">${icon("bolt")} Acelerar com a placa de vídeo (~1 GB)</button>`)}
        ${field("Ler respostas em voz alta", "Na conversa por voz (Ctrl+K › Conversa por voz). Voz neural local (Kokoro). Código não é lido.", toggle("voice_replies", st.voice_replies))}</div>`;
      break;
    case "sobre":
      html = `<h1>Sobre</h1><div class="group" style="padding:20px"><div class="row"><img src="logo.svg" style="width:64px"><div><h2 style="margin:0">Órbita <span class="tag grad" style="vertical-align:middle">v${esc(S.version || "")}</span></h2><span style="color:var(--muted)">Seu agente pessoal de IA — suas regras, seu computador.</span></div></div>
        <div class="row" style="margin-top:16px"><button class="btn small" data-open="data">${icon("folder")} Pasta de dados</button><button class="btn small" data-open="logs">${icon("file")} Logs</button><button class="btn small" data-open="roadmap">${icon("book")} ROADMAP</button><button class="btn small" data-open="license">${icon("shield")} Licença GPL v3</button></div>
        <p style="color:var(--muted);font-size:12.5px;margin:16px 0 0">Software livre sob a GNU GPL v3: você pode usar, estudar, modificar e compartilhar. Versões modificadas distribuídas devem continuar abertas sob a mesma licença.</p></div>
        <div class="group"><h3>Atualizações</h3>
        ${field("Situação", updateStatusText(), `<div class="row"><button class="btn small" id="up-check">${icon("refresh")} Procurar agora</button>${S.update && S.update.available ? `<button class="btn primary small" id="up-open">${icon("download")} Ver novidades</button>` : ""}</div>`)}
        ${field("Verificar sozinho", "Ao abrir, consulta o GitHub (no máximo a cada 6 horas) e avisa quando há melhorias no programa. Nada é baixado sem você confirmar.", toggle("update_check", st.update_check !== false))}</div>`;
      break;
  }
  $("#set-body").innerHTML = `<div class="set-in">${html}</div>`;
  bindSettings();
}
async function setSetting(key, value, silent) {
  S = await call("setSetting", key, JSON.stringify(value));
  renderTopbar(); renderAgents();
  if (!silent) toast("success", "Salvo", "Configuração atualizada.", 1800);
}
function bindSettings() {
  const body = $("#set-body");
  $$("[data-set]", body).forEach(t => t.addEventListener("change", () => setSetting(t.dataset.set, t.checked)));
  $$("[data-text]", body).forEach(t => t.addEventListener("change", () => setSetting(t.dataset.text, t.value.trim())));
  $$("[data-num]", body).forEach(t => t.addEventListener("change", () => setSetting(t.dataset.num, +t.value || 0)));
  $$("[data-seg]", body).forEach(g => $$("button", g).forEach(b => b.addEventListener("click", async () => {
    $$("button", g).forEach(x => x.classList.toggle("on", x === b));
    if (g.dataset.seg === "theme") applyTheme(b.dataset.v);
    await setSetting(g.dataset.seg, b.dataset.v);
  })));
  $$("[data-savekey]", body).forEach(b => b.addEventListener("click", async () => {
    const env = b.dataset.savekey, input = $(`[data-key="${env}"]`, body);
    if (!input.value.trim()) return;
    S = await call("saveApiKey", env, input.value.trim()); input.value = "";
    toast("success", "Chave salva", env); renderSettings();
  }));
  $$("[data-grok]", body).forEach(b => b.addEventListener("click", async () => {
    const r = await call("grok", b.dataset.grok);
    if (r && r.message) toast("info", "Grok", r.message);
    if (r && r.status) { S.grok = r.status; renderSettings(); }
  }));
  $$("[data-open]", body).forEach(b => b.addEventListener("click", () => call("openPath", b.dataset.open)));
  const openProject = $("#open-project"); if (openProject) openProject.onclick = () => projectDialog();
  const onb = $("#re-onb"); if (onb) onb.onclick = showOnboarding;
  const gotoApi = $("#goto-api"); if (gotoApi) gotoApi.onclick = () => { settingsSection = "api"; renderSettings(); };
  if (settingsSection === "api") bindManualApi();
  const cat = $("#cat-open"); if (cat) cat.onclick = () => call("openPath", "catalog");
  if (settingsSection === "voz") {
    call("voiceGpuStatus").then(renderVoiceGpu);
    call("sttStatus").then(s => {
      const el = $("#stt-status"); if (!el || !s) return;
      el.innerHTML = s.kind === "cloud" ? `<span style="color:var(--ok)">● Usando ${esc(s.label)}</span> — rápido em qualquer PC.`
        : s.wanted_cloud ? `<span style="color:var(--warn)">● Sem chave da Groq ou OpenAI</span>: usando ${esc(s.label)} até você colar uma chave.`
        : `● Usando ${esc(s.label)}.`;
    });
  }
  const vg = $("#vg-install");
  if (vg) vg.onclick = () => { call("installVoiceGpu"); renderVoiceGpu({ cuda: true, libs: false, installing: true }); };
  const upCheck = $("#up-check");
  if (upCheck) upCheck.onclick = () => { upCheck.disabled = true; upCheck.innerHTML = `<span class="spin"></span> Procurando…`; call("checkUpdate"); };
  const upOpen = $("#up-open"); if (upOpen) upOpen.onclick = () => updateModal(S.update);
  if (settingsSection === "modelos") bindModels();
}
// Chave de API colada no lugar do modelo (mesma regra do Python, em gui.looks_like_secret).
function looksLikeKey(text) {
  const t = (text || "").trim();
  if (!t || /[\/: ]/.test(t)) return false;
  const longest = Math.max(0, ...t.split(/[-_.]/).map(s => s.length));
  const mixed = /[A-Z]/.test(t) && /[a-z]/.test(t) && /\d/.test(t);
  return mixed && (longest >= 24 || (/^(sk|sk-or|sk-ant|rv|gsk|xai|pplx|csk|r8|hf|ghp|AIza)[-_]?[A-Za-z0-9]/i.test(t) && t.length >= 24));
}
function normSearch(s) {
  return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}
function matchModelQuery(name, query) {
  const q = normSearch(query).trim();
  if (!q) return true;
  const hay = normSearch(name);
  return q.split(/\s+/).every(part => hay.includes(part));
}
function bindSearchableModels({ provEl, modelEl, searchEl, countEl, listEl, warnEl, hintEl, refreshBtn, submitBtn, boxEl, isActive, onPick }) {
  let selIdx = 0, shown = [];
  const autoFetched = new Set();
  const current = () => S.providers.find(p => p.id === provEl.value) || {};
  const refresh = () => {
    if (!provEl.value) return;
    call("refreshModels", provEl.value);
    if (hintEl) hintEl.textContent = "buscando modelos…";
  };
  const markSel = () => {
    const items = $$("[data-m]", listEl);
    items.forEach((b, i) => b.classList.toggle("sel", i === selIdx));
    if (items[selIdx]) items[selIdx].scrollIntoView({ block: "nearest" });
  };
  const render = (resetIdx = false) => {
    const provId = provEl.value;
    if (boxEl) boxEl.hidden = !provId;
    const models = (current().models || []).filter(m => !looksLikeKey(m));
    const bad = looksLikeKey(modelEl.value);
    if (warnEl) warnEl.innerHTML = bad ? `${icon("alert")}<span>Isso parece uma <b>chave de API</b>, não o nome de um modelo. A chave vai em Chaves de API; aqui, clique em um modelo da lista.</span>` : "";
    if (submitBtn) submitBtn.disabled = bad;
    const sq = searchEl.value.trim(), mq = modelEl.value.trim();
    const q = sq || (!bad && mq && !models.some(m => normSearch(m) === normSearch(mq)) ? mq : "");
    const filtered = q ? models.filter(m => matchModelQuery(m, q)) : models;
    shown = filtered.slice(0, 300);
    if (countEl) countEl.textContent = `${filtered.length} de ${models.length}`;
    if (resetIdx) {
      const actIdx = shown.findIndex(m => isActive(provId, m));
      selIdx = actIdx >= 0 ? actIdx : 0;
    } else {
      selIdx = Math.max(0, Math.min(selIdx, Math.max(0, shown.length - 1)));
    }
    listEl.innerHTML = !provId ? ""
      : !models.length ? `<div class="empty">Nenhum modelo carregado ainda. Clique em ${icon("refresh")} para buscar a lista no provedor.</div>`
      : shown.map((m, i) => {
          const on = isActive(provId, m);
          return `<button type="button" class="mp ${on ? "on" : ""} ${i === selIdx ? "sel" : ""}" data-m="${esc(m)}" title="Usar ${esc(m)}">${icon(on ? "check" : "cpu")}<span>${esc(m)}</span></button>`;
        }).join("") + (filtered.length ? "" : `<div class="empty">Nenhum modelo com “${esc(q)}”. Para usar mesmo assim, digite no campo Modelo.</div>`);
    $$("[data-m]", listEl).forEach((b, i) => {
      b.onclick = () => { selIdx = i; onPick(b.dataset.m); };
    });
    if (hintEl) hintEl.textContent = models.length ? `${filtered.length} de ${models.length} ${models.length === 1 ? "modelo disponível" : "modelos disponíveis"} · setas + Enter ou clique para usar` : "";
    if (provId && !models.length && !autoFetched.has(provId)) {
      autoFetched.add(provId);
      refresh();
    }
  };
  const onKey = e => {
    if (!shown.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); selIdx = Math.min(selIdx + 1, shown.length - 1); markSel(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); selIdx = Math.max(selIdx - 1, 0); markSel(); }
    else if (e.key === "Enter" && shown[selIdx]) { e.preventDefault(); e.stopPropagation(); onPick(shown[selIdx]); }
  };
  searchEl.addEventListener("input", () => { selIdx = 0; render(false); });
  searchEl.addEventListener("keydown", onKey);
  modelEl.addEventListener("input", () => render(false));
  modelEl.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") onKey(e);
  });
  provEl.onchange = () => {
    searchEl.value = "";
    const first = (current().models || [""])[0] || "";
    if (provEl.id === "m-prov" || !provEl.value) modelEl.value = provEl.value ? first : "";
    else if (!modelEl.value.trim()) modelEl.value = first;
    render(true);
  };
  if (refreshBtn) refreshBtn.onclick = refresh;
  render(true);
  if (looksLikeKey(modelEl.value) && provEl.value) refresh();
  return render;
}
let modelList = null;   // redesenha a lista de Configurações › Modelos quando chegam modelos novos
function bindModels() {
  const prov = $("#m-prov"), input = $("#m-model");
  const apply = async model => {
    if (looksLikeKey(model)) return toast("error", "Isso é uma chave", "A chave vai em Configurações › Chaves de API. Aqui escolha um modelo da lista.", 7000);
    const res = await call("selectModel", prov.value, model);
    if (!res || res.error) return toast("error", "Modelo", (res && res.error) || "Não deu para usar esse modelo.", 7000);
    S = res.state; renderAll(); renderSettings();
    toast("success", "Modelo ativo", S.model_label + (res.bound_profile ? ` · perfil ${res.bound_profile}` : ""));
    const p = S.providers.find(x => x.id === prov.value);
    if (p && !p.has_credentials) toast("warn", "Falta acesso", p.type === "grok_cli" ? "Entre na conta Grok em Configurações › Conta Grok." : `Configure ${p.api_key_env} em Chaves de API.`, 6000);
  };
  modelList = bindSearchableModels({
    provEl: prov,
    modelEl: input,
    searchEl: $("#m-search"),
    countEl: $("#m-count"),
    listEl: $("#m-list"),
    warnEl: $("#m-warn"),
    hintEl: $("#m-hint"),
    refreshBtn: $("#m-refresh"),
    submitBtn: $("#m-apply"),
    isActive: (provId, m) => S.provider === provId && S.model === m,
    onPick: m => { input.value = m; apply(m); },
  });
  $("#m-apply").onclick = () => apply(input.value.trim());
  $("#pull-btn").onclick = () => { const n = $("#pull-name").value.trim(); if (n) { call("pullModel", n); toast("info", "Ollama", `Baixando ${n}…`); } };
  call("localModels").then(list => {
    $("#local-models").innerHTML = (list && list.length) ? list.map(m => `<div class="model-row"><span class="nm">${esc(m.name)}</span><span class="sz">${esc(m.size)} · ${esc(m.params || "")}</span><button class="btn small" data-use-local="${esc(m.name)}">${S.provider === "ollama" && S.model === m.name ? "Em uso ✓" : "Usar"}</button></div>`).join("")
      : `<div class="empty">Ollama não está rodando ou não há modelos instalados.</div>`;
    $$("[data-use-local]").forEach(b => b.addEventListener("click", async () => { const r = await call("selectModel", "ollama", b.dataset.useLocal); S = r.state; renderAll(); renderSettings(); toast("success", "Modelo local ativo", b.dataset.useLocal); }));
  });
}
function bindManualApi() {
  const body = $("#set-body");
  $("#api-probe").onclick = () => {
    const url = $("#api-url").value.trim();
    if (!url) return toast("warn", "API", "Cole o endereço da API.");
    $("#probe-status").textContent = "Verificando modelos…";
    $("#probe-models").innerHTML = "";
    call("probeProvider", JSON.stringify({ url, key: $("#api-key").value }));
  };
  $("#api-save").onclick = async () => {
    const data = {
      label: $("#api-name").value.trim(),
      url: $("#api-url").value.trim(),
      key: $("#api-key").value,
      model: $("#api-model").value.trim(),
      use: true,
    };
    if (!data.label || !data.url) return toast("warn", "API", "Informe o nome e o endereço.");
    if (!data.model) return toast("warn", "API", "Informe o modelo, ou clique em Verificar modelos e escolha um.");
    if (looksLikeKey(data.model) || (data.key && data.model === data.key.trim()))
      return toast("error", "Modelo", "O campo Modelo está com a chave de API. A chave vai só no campo Chave; no Modelo, o nome (clique em Verificar modelos para ver a lista).", 8000);
    const res = await call("addProvider", JSON.stringify(data));
    if (!res || res.error) return toast("error", "API", (res && res.error) || "Não deu para salvar.");
    S = res.state;
    renderAll();
    renderSettings();
    toast("success", "API pronta", `${data.label} · ${data.model}`);
  };
  $$("[data-use-api]", body).forEach(b => b.addEventListener("click", async () => {
    const provider = S.providers.find(p => p.id === b.dataset.useApi);
    const model = (provider?.models || [])[0];
    if (!model) return toast("warn", "API", "Essa API não tem um modelo salvo. Adicione de novo informando o modelo.");
    const res = await call("selectModel", provider.id, model);
    S = res.state;
    renderAll();
    renderSettings();
    toast("success", "Modelo ativo", S.model_label);
  }));
  $$("[data-drop-api]", body).forEach(b => b.addEventListener("click", async () => {
    const provider = S.providers.find(p => p.id === b.dataset.dropApi);
    if (!await confirmBox("Remover esta API?", provider ? provider.label : "Ela sai da lista. A chave continua no .env deste PC.")) return;
    const res = await call("removeProvider", b.dataset.dropApi);
    if (!res || res.error) return toast("error", "API", (res && res.error) || "Não deu para remover.");
    S = res.state;
    renderAll();
    renderSettings();
    toast("success", "API removida", provider ? provider.label : "");
  }));
}
function onProbe(e) {
  const status = $("#probe-status");
  const list = $("#probe-models");
  if (!status || !list) return;
  if (!e.ok) {
    status.textContent = e.error || "Não deu para verificar.";
    return;
  }
  if (e.base_url && $("#api-url")) $("#api-url").value = e.base_url;
  const shown = (e.models || []).slice(0, 80);
  status.textContent = `${e.models.length} modelo(s) encontrado(s). Clique em um para usar.`;
  list.innerHTML = shown.map(m => `<button type="button" class="btn small" data-pick-model="${esc(m)}">${esc(m)}</button>`).join("")
    + (e.models.length > shown.length ? `<span class="status">e mais ${e.models.length - shown.length}. Digite o nome no campo Modelo.</span>` : "");
  $$("[data-pick-model]", list).forEach(b => b.addEventListener("click", () => { $("#api-model").value = b.dataset.pickModel; }));
}
async function useProject(res) {
  if (!res || res.error) {
    toast("error", "Projeto", (res && res.error) || "Não deu para abrir essa pasta.");
    return;
  }
  const fresh = $("#pj-fresh") ? $("#pj-fresh").checked : false;
  S = res.state;
  closeModal();
  if (fresh) {
    await call("newConversation");
    resetChat();
    go("chat");
  } else {
    renderAll();
    if ($("#page-settings").classList.contains("active")) renderSettings();
  }
  toast("success", "Projeto aberto", S.workspace, 3200);
}
function projectDialog() {
  const current = S.workspace_set ? (S.workspace || "") : "";
  const parent = current ? current.replace(/[\\/][^\\/]+$/, "") : (S.projects_parent || "");
  const recent = (S.recent_workspaces || []).filter(p => p !== current).slice(0, 6);
  openModal(`<div class="modal"><div class="row" style="justify-content:space-between"><h2 style="margin:0">Projeto</h2>
      <button class="icon-btn" id="pj-close" title="Fechar (Esc)">${icon("x")}</button></div>
    <p class="sub" style="margin-top:6px">O agente lê, cria e edita arquivos dentro da pasta do projeto.</p>
    <div class="pathbox">${current ? esc(current) : "Nenhum projeto aberto — o agente está usando a sua pasta de usuário."}</div>
    <div class="actions" style="justify-content:flex-start">
      <button class="btn primary" id="pj-open">${icon("folder")} Abrir pasta existente</button>
      <button class="btn" id="pj-new">${icon("plus")} Criar projeto novo</button>
    </div>
    <div id="pj-create" hidden>
      <div class="stack">
        <label for="pj-name">Nome do projeto</label>
        <input class="inp" id="pj-name" placeholder="ex.: site-da-loja">
        <label for="pj-parent">Criar dentro de</label>
        <div class="row"><input class="inp" id="pj-parent" style="flex:1" value="${esc(parent)}"><button class="btn small" id="pj-parent-pick" title="Escolher pasta">${icon("folder")}</button></div>
      </div>
      <div class="actions" style="justify-content:flex-start"><button class="btn primary" id="pj-create-go">${icon("check")} Criar e abrir</button></div>
    </div>
    ${recent.length ? `<div class="stack"><label>Recentes</label>${recent.map(p => `<button class="recent" data-recent="${esc(p)}">${icon("folder")}<span><b>${esc(p.split(/[\\/]/).pop())}</b><small>${esc(p)}</small></span></button>`).join("")}</div>` : ""}
    <label class="row" style="margin-top:14px"><span class="toggle"><input type="checkbox" id="pj-fresh" ${S.conversation_id ? "" : "checked"}><span></span></span> Começar uma conversa nova neste projeto</label>
  </div>`);
  const guard = () => busy && (toast("warn", "Aguarde", "O agente ainda está trabalhando nesta conversa."), true);
  $("#pj-close").onclick = closeModal;
  $("#pj-open").onclick = async () => {
    if (guard()) return;
    const folder = await call("pickFolder", current || parent);
    if (folder) useProject(await call("setWorkspace", folder));
  };
  $("#pj-new").onclick = () => { $("#pj-create").hidden = false; $("#pj-fresh").checked = true; $("#pj-name").focus(); };
  $("#pj-parent-pick").onclick = async () => {
    const folder = await call("pickFolder", $("#pj-parent").value);
    if (folder) $("#pj-parent").value = folder;
  };
  $("#pj-name").addEventListener("keydown", e => { if (e.key === "Enter") $("#pj-create-go").click(); });
  $("#pj-create-go").onclick = async () => {
    if (guard()) return;
    const name = $("#pj-name").value.trim();
    if (!name) return toast("warn", "Projeto", "Dê um nome para a pasta.");
    useProject(await call("createWorkspace", JSON.stringify({ parent: $("#pj-parent").value.trim(), name })));
  };
  $$("[data-recent]", $("#modal-root")).forEach(b => b.addEventListener("click", async () => {
    if (guard()) return;
    useProject(await call("setWorkspace", b.dataset.recent));
  }));
}
function onModels(e) {
  const p = S.providers.find(x => x.id === e.provider); if (p && e.models.length) p.models = e.models.filter(m => !looksLikeKey(m));
  if ($("#m-prov") && $("#m-prov").value === e.provider && modelList) {
    modelList(true);
    if (!e.models.length) $("#m-hint").textContent = "O provedor não devolveu a lista. Confira a chave em Chaves de API ou digite o nome do modelo.";
  }
  if ($("#pe-prov") && $("#pe-prov").value === e.provider && peModelList) {
    peModelList(true);
  }
  if ($("#mm-prov") && $("#mm-prov").value === e.provider && quickModelList) {
    quickModelList(true);
    if (!e.models.length) $("#mm-hint").textContent = "O provedor não devolveu a lista. Confira a chave em Configurações › Chaves de API.";
  }
}
function onPull(e) {
  const box = $("#pull-progress"); if (!box) { if (e.done) toast(e.error ? "error" : "success", "Ollama", e.error || `${e.model} pronto!`); return; }
  const pct = e.total ? Math.round(e.completed / e.total * 100) : 0;
  box.innerHTML = `<div style="font-size:12px;color:var(--muted)">${esc(e.model)} · ${esc(e.status || "")} ${pct ? pct + "%" : ""}</div><div class="progress"><i style="width:${pct}%"></i></div>`;
  if (e.done) { toast(e.error ? "error" : "success", "Ollama", e.error || `${e.model} pronto para usar!`); setTimeout(() => settingsSection === "modelos" && renderSettings(), 600); }
}

// ── Primeira execução ──────────────────────────────────────────────────────────
function showOnboarding() {
  const data = { user_name: S.settings.user_name || "", mode: S.provider === "ollama" ? "local" : "cloud", provider: S.provider, model: S.model, workspace: S.settings.default_workspace || "", permission_mode: S.settings.permission_mode || "auto", voice_replies: !!S.settings.voice_replies, key: "" };
  let step = 0;
  const steps = [
    () => `<h2>Bem-vindo! Como posso te chamar?</h2><p class="sub">Vamos deixar o agente pronto para os seus primeiros trabalhos em menos de um minuto.</p>
      <input class="inp" id="ob-name" placeholder="Seu nome" value="${esc(data.user_name)}">`,
    () => `<h2>Qual IA vai trabalhar com você?</h2><p class="sub">Dá para trocar a qualquer momento em Configurações › Modelos.</p>
      <div class="choice ${data.mode === "local" ? "on" : ""}" data-mode="local"><div class="ci">${icon("cpu")}</div><div><b>Local (Ollama) — grátis e privado</b><span>Roda na sua placa de vídeo. ${(S.local_models || []).length} modelo(s) instalado(s).</span></div></div>
      <div class="choice ${data.mode === "cloud" ? "on" : ""}" data-mode="cloud"><div class="ci">${icon("globe")}</div><div><b>Nuvem — DeepSeek, GPT, Claude, Gemini…</b><span>Mais inteligente para tarefas longas; usa uma chave de API.</span></div></div>
      <div class="choice ${data.mode === "grok" ? "on" : ""}" data-mode="grok"><div class="ci">${icon("bolt")}</div><div><b>Grok Build com a sua conta xAI</b><span>${S.grok?.logged_in ? "Conta já conectada neste PC ✓" : "Login pelo navegador."}</span></div></div>
      <div id="ob-detail" style="margin-top:10px"></div>`,
    () => `<h2>Onde vamos trabalhar?</h2><p class="sub">A pasta onde o agente lê, cria e edita arquivos por padrão.</p>
      <div class="row"><input class="inp" id="ob-ws" style="flex:1" value="${esc(data.workspace)}" placeholder="ex.: E:\\Projetos"><button class="btn" id="ob-pick">${icon("folder")} Escolher</button></div>
      <h2 style="margin-top:22px">Quanta liberdade?</h2>
      ${[["perguntar", "shield", "Perguntar", "Confirma qualquer alteração antes de fazer."], ["auto", "sparkle", "Automático (recomendado)", "Edita arquivos sozinho; pergunta antes de executar comandos ou controlar o PC."], ["livre", "bolt", "Livre", "Age sem pedir confirmação."]]
        .map(([v, ic, t, s]) => `<div class="choice ${data.permission_mode === v ? "on" : ""}" data-perm="${v}"><div class="ci">${icon(ic)}</div><div><b>${t}</b><span>${s}</span></div></div>`).join("")}`,
    () => `<h2>Tudo pronto${data.user_name ? ", " + esc(data.user_name.split(" ")[0]) : ""}! 🚀</h2><p class="sub">Dicas rápidas:</p>
      <div class="choice"><div class="ci">${icon("command")}</div><div><b>Ctrl+K</b><span>Paleta de comandos: trocar perfil, modelo, permissões…</span></div></div>
      <div class="choice"><div class="ci">${icon("users")}</div><div><b>Equipe</b><span>Peça "divida entre a equipe" para agentes trabalharem em paralelo.</span></div></div>
      <div class="choice"><div class="ci">${icon("wave")}</div><div><b>Voz</b><span>Clique no microfone para falar. <label class="row" style="display:inline-flex;margin-left:6px"><span class="toggle"><input type="checkbox" id="ob-voice" ${data.voice_replies ? "checked" : ""}><span></span></span> ler respostas em voz alta</label></span></div></div>`,
  ];
  const render = () => {
    openModal(`<div class="modal onb"><div class="hero"><img src="logo.svg"><div class="steps-dots">${steps.map((_, i) => `<i class="${i <= step ? "on" : ""}"></i>`).join("")}</div></div>
      <div class="body">${steps[step]()}<div class="actions">${step ? `<button class="btn" id="ob-back">Voltar</button>` : ""}<button class="btn primary" id="ob-next">${step === steps.length - 1 ? "Começar" : "Continuar"}</button></div></div></div>`, false);
    if ($("#ob-name")) $("#ob-name").oninput = e => data.user_name = e.target.value;
    $$("[data-mode]").forEach(c => c.onclick = () => { data.mode = c.dataset.mode; $$("[data-mode]").forEach(x => x.classList.toggle("on", x === c)); detail(); });
    $$("[data-perm]").forEach(c => c.onclick = () => { data.permission_mode = c.dataset.perm; $$("[data-perm]").forEach(x => x.classList.toggle("on", x === c)); });
    if ($("#ob-ws")) { $("#ob-ws").oninput = e => data.workspace = e.target.value; $("#ob-pick").onclick = async () => { const f = await call("pickFolder", data.workspace); if (f) { data.workspace = f; $("#ob-ws").value = f; } }; }
    if ($("#ob-voice")) $("#ob-voice").onchange = e => data.voice_replies = e.target.checked;
    if ($("#ob-detail")) detail();
    if ($("#ob-back")) $("#ob-back").onclick = () => { step--; render(); };
    $("#ob-next").onclick = async () => {
      if (step < steps.length - 1) { step++; return render(); }
      S = await call("completeOnboarding", JSON.stringify(data)); closeModal(); renderAll();
      toast("success", "Configuração concluída", `${S.profile.name} · ${S.model_label}`);
    };
  };
  const detail = () => {
    const box = $("#ob-detail"); if (!box) return;
    if (data.mode === "local") {
      const list = S.local_models || [];
      if (!list.includes(data.model)) data.model = list[0] || data.model;
      data.provider = "ollama";
      box.innerHTML = list.length ? `<select class="inp" id="ob-local">${list.map(m => `<option ${m === data.model ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>` : `<div class="empty" style="padding:10px">Nenhum modelo local encontrado — dá para baixar em Configurações › Modelos.</div>`;
      if ($("#ob-local")) $("#ob-local").onchange = e => data.model = e.target.value;
    } else if (data.mode === "cloud") {
      const clouds = S.providers.filter(p => p.api_key_env);
      if (!clouds.find(p => p.id === data.provider)) { data.provider = "deepseek"; data.model = "deepseek-chat"; }
      box.innerHTML = `<div class="row"><select class="inp" id="ob-prov" style="flex:1">${clouds.map(p => `<option value="${p.id}" ${p.id === data.provider ? "selected" : ""}>${esc(p.label)}${p.has_credentials ? " ✓" : ""}</option>`).join("")}</select><input class="inp" id="ob-model" style="flex:1" value="${esc(data.model)}"></div>
        <input class="inp" id="ob-key" type="password" style="margin-top:8px" placeholder="Chave de API (fica só no .env deste PC)">`;
      $("#ob-prov").onchange = e => { data.provider = e.target.value; data.model = (S.providers.find(p => p.id === data.provider).models || [""])[0]; $("#ob-model").value = data.model; };
      $("#ob-model").oninput = e => data.model = e.target.value;
      $("#ob-key").oninput = e => data.key = e.target.value;
    } else {
      data.provider = "grok"; data.model = "grok-4.7";
      box.innerHTML = S.grok?.logged_in ? `<div class="sub" style="color:var(--ok)">✓ Conta conectada.</div>` : `<button class="btn" id="ob-grok">${icon("user")} Entrar na conta xAI</button>`;
      if ($("#ob-grok")) $("#ob-grok").onclick = () => call("grok", S.grok?.installed ? "login" : "install");
    }
  };
  render();
}
