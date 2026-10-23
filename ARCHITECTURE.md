# Arquitetura do Órbita

```
Você ──► GUI (agent/gui.py) / terminal / voz
            │  AgentWorker (thread)          eventos: texto, ferramentas, subagentes, imagens
            ▼
         Brain (core/brain.py) ── perfil ativo + provedor:modelo + serviços
            │
            ▼
         AgentSession (core/agent_loop.py)   ← o loop agêntico
            │  1. monta o prompt de sistema: base + perfil (prompt de injeção) + ambiente
            │     + AGENTS.md da pasta de trabalho + skills + MCP + equipe + memória
            │  2. corta o contexto ao orçamento (modo de economia)
            │  3. chama o provedor (streaming) ──► providers.py: Ollama | OpenAI-compatível | Anthropic
            │  4. executa ferramentas pedidas (permissões, paralelo seguro, detector de loop)
            │  5. repete até a resposta final, limite de passos ou freio de tokens
            ▼
         ToolRegistry (core/tools.py)
            ├─ embutidas (actions/builtin_tools.py): arquivos, shell + verify_project (gates, risco exec), web, PC,
            │   memória, skills, delegate_task (equipe com contrato estruturado), find_tools (MCP adiado)
            ├─ generate_image (actions/image_gen.py): style anchor, negative_prompt, shot_id + sidecar .meta.json
            └─ MCP (core/mcp_hub.py): cada servidor em data/mcp.json vira ferramentas mcp__<srv>__<tool>
```

## Módulos

| Arquivo | Papel |
|---|---|
| `agent/core/settings.py` | Preferências (`data/settings.json`), catálogo de provedores, chaves no `.env`, vínculo modelo→perfil |
| `agent/core/providers.py` | Adaptadores de IA com formato interno único de mensagens; streaming; detecção de modelo sem ferramentas |
| `agent/core/deepseek_web.py` | Conta DeepSeek pelo site em Playwright: login humano, perfil dedicado/CDP local, texto e raciocínio SSE, ferramentas por prompt; busca e exclusão da própria sessão opcionais |
| `agent/core/browser_chat.py` · `agent/ui/browser.html` | Chat em loopback com token por execução, streaming, aprovações interativas, seletores, anexos textuais e cancelamento; usa `Brain.run_turn` |
| `agent/core/prompt_polling.py` | Fila HTTP explícita de pedidos: cotas, deduplicação em memória, cancelamento e mesmas permissões do loop |
| `agent/ui/terminal.py` | Markdown ao vivo com Rich, raciocínio, ferramentas e pausa do desenho para autorização no terminal |
| `agent/core/grok_cli.py` | Grok Build (xAI) com a conta do usuário: login/estado do CLI oficial e provedor "agente externo" (`grok -p --resume`) |
| `agent/core/grok_bridge.py` | Ponte MCP "orbita" para o Grok Build: com ele como principal, chama a equipe (`delegate_task`), skills, ferramentas de criação e `check_web_page` do Órbita, com as permissões de sempre |
| `agent/core/agent_loop.py` | `AgentSession`: loop, permissões, contexto, freio de tokens, ferramentas por prompt, delegação |
| `agent/core/tools.py` | `Tool`, `ToolRegistry`, `ToolResult`, decorador `tool()`; busca de ferramentas adiadas |
| `agent/core/profiles.py` | Perfis/equipe (`data/profiles/*.json`): prompt de sistema, prompt inicial, modelo, ferramentas |
| `agent/core/mcp_hub.py` | Cliente MCP (stdio/HTTP) numa thread asyncio; importação de configs do Claude/Cursor |
| `agent/core/ghidra_setup.py` | Ghidra do REA pelo backend: aponta `GHIDRA_INSTALL_DIR` no processo ou baixa em segundo plano (SHA-256, extração atômica); estado só leitura no painel |
| `agent/core/skills.py` | Skills `SKILL.md` + plugins. `when` vira roteador no prompt; `context: models` anexa a tabela só ao carregar |
| `agent/core/usage.py` | Medidor de tokens (`data/usage.json`) e políticas de economia |
| `agent/core/brain.py` | Fachada: liga tudo, seleção de perfil/modelo, modos texto/voz |
| `agent/core/studio3d.py` · `agent/actions/studio3d.py` · `creative_apps.py` | Estúdio 3D: diagnóstico local, Unreal Remote Control, ponte Unity autenticada, Blender por script e CLI Godot/OpenSCAD; risco exec nas mutações e reservas por sessão nos editores |
| `agent/integrations/unity/OrbitaBridge.cs` | Recurso instalado sob autorização em Assets/Editor; HTTP loopback com token, fila para a thread Unity e Undo; não entra no jogo compilado |
| `agent/gui.py` | Janela (QWebEngine), ponte `Api` (QWebChannel) com a página, worker do agente, bandeja e notificações |
| `agent/ui/web/` | Interface: `index.html`, `app.css` (design system "Órbita"), `app.js` (sem dependências externas), `logo.svg` |
| `agent/ui/render.py` | Markdown → HTML **sanitizado** (sem HTML cru, sem `javascript:`) e texto para a voz |
| `agent/ui/brand.py` | Nome, ícone (.ico gerado do SVG) e registro do app na barra de tarefas |
| `agent/core/routing.py` | Catálogo de capacidades (`data/model_catalog.json`) e escolha do melhor modelo por especialidade (só com a equipe em "Automático"; o padrão é o ajudante usar o modelo do principal) |
| `agent/core/capabilities.py` | Nível de cada modelo (ponta / padrão / compacto): mais autonomia e passos para os de ponta, "modo foco" para os locais pequenos |
| `agent/core/checkpoints.py` · `mentions.py` · `updater.py` | Pontos de restauração por resposta (git sombra) · `@arquivo` · atualização pelo GitHub |
| `agent/core/teamwork.py` · `integration.py` | Quando sugerir equipe e quantos ajudantes em paralelo · checagem HTML × CSS × JS depois da delegação |
| `agent/actions/web_check.py` | Ferramenta `check_web_page`: abre a página num Chromium invisível (processo separado) e relata erros, recursos, links e overflow |
| `agent/voice/dictation.py` | Ditado no campo de mensagem: grava até o 2º clique, texto parcial ao vivo, final preciso; GPU (CUDA) com volta automática para a CPU |
| `agent/core/conversations.py` | Conversas salvas (`data/conversations/`) e conversão para blocos da interface |
| `agent/memory/memory_manager.py` | Histórico diário e fatos de longo prazo |
| `agent/voice/` | Microfone (faster-whisper + Silero VAD), voz (Kokoro/Piper/Windows), atalho |

## Decisões importantes

- **Formato interno único de mensagens** (ver docstring de `providers.py`). Cada provedor converte na
  hora de enviar; o Claude recebe de volta seus blocos originais (`_native`) para preservar o raciocínio.
- **Ferramentas por prompt**: se o modelo não aceita tool-calling nativo, o loop injeta o catálogo no
  prompt e lê blocos `<tool_call>`; qualquer modelo vira agente.
- **Motor lento (REA)**: com `ready_check`, o hub faz o check-in em segundo plano ao conectar e cada chamada pesada roda
  em segundo plano; passou de 5 s, a tool volta `warming_up` na hora e a mesma chamada repetida reaproveita a execução.
- **MCP adiado**: servidores com muitas ferramentas (REA: 207) não entram no contexto; o modelo usa
  `find_tools`. `always_load` define um "kit inicial" sempre visível.
- **Ferramentas MCP rodam em sequência** (têm estado no servidor); só leituras embutidas rodam em paralelo.
- **Permissões por risco**: `read` nunca pergunta; `write` pergunta no modo *perguntar*; `exec` pergunta
  nos modos *perguntar* e *auto*; *livre* nunca pergunta. Um caminho só (`_authorize`) para o loop, a ponte do
  Grok e a verificação da equipe; o perfil (grupos e `mcp_servers`) vale também para MCP chamado pelo nome.
- **Economia**: resultados antigos de ferramentas são encurtados, turnos velhos saem do contexto,
  saídas longas são cortadas e o freio pergunta antes de ultrapassar o orçamento por tarefa/dia. Se nem o turno
  atual cabe (modelo local), `_fit_turn` mira o orçamento menos 5% de folga, encurta guardando começo e fim,
  troca passos antigos por uma linha (ferramenta, tamanho, erro) e dá ao último passo até 70%; skill encurta por último.
  O teto é o menor entre o modo de economia e a janela do modelo (`capabilities.context_window`), até 1M. A
  compactação nunca desiste: modelo econômico, principal e, por fim, resumo extraído do histórico.
- **Subagentes** compartilham o botão Parar e o orçamento do principal; profundidade máxima 2.
- **Conversa temporária** usa `MemoryManager(memory_only=True)` sem ler/gravar fatos anteriores, e não salva a conversa
  nem cria checkpoints. Nova conversa descarta essa memória; sair do modo restaura a memória persistente original.
  A política não apaga arquivos criados por ferramentas, logs técnicos ou dados retidos pelo provedor.
- **Anexos e menções**: `@arquivo` é expandido somente na entrada original da pessoa (GUI/terminal). O conteúdo de
  anexos ou fontes web não é reinterpretado como pedido para ler outros arquivos. Seleções de pastas têm cotas e
  excluem links e arquivos de segredos.

## Dados (pasta `data/`)

`settings.json` · `profiles/*.json` · `mcp.json` · `usage.json` · `model_catalog.json` · `conversations/` · `artifacts/` (imagens geradas/MCP) ·
`screenshots/` · `logs/agent.log` e `logs/mcp-<servidor>.log`
