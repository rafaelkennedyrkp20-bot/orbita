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
            ├─ embutidas (actions/builtin_tools.py): arquivos, shell, web, PC, memória, skills,
            │   delegate_task (equipe), find_tools (MCP adiado)
            ├─ generate_image (actions/image_gen.py)
            └─ MCP (core/mcp_hub.py): cada servidor em data/mcp.json vira ferramentas mcp__<srv>__<tool>
```

## Módulos

| Arquivo | Papel |
|---|---|
| `agent/core/settings.py` | Preferências (`data/settings.json`), catálogo de provedores, chaves no `.env`, vínculo modelo→perfil |
| `agent/core/providers.py` | Adaptadores de IA com formato interno único de mensagens; streaming; detecção de modelo sem ferramentas |
| `agent/core/grok_cli.py` | Grok Build (xAI) com a conta do usuário: login/estado do CLI oficial e provedor "agente externo" (`grok -p --resume`) |
| `agent/core/agent_loop.py` | `AgentSession`: loop, permissões, contexto, freio de tokens, ferramentas por prompt, delegação |
| `agent/core/tools.py` | `Tool`, `ToolRegistry`, `ToolResult`, decorador `tool()`; busca de ferramentas adiadas |
| `agent/core/profiles.py` | Perfis/equipe (`data/profiles/*.json`): prompt de sistema, prompt inicial, modelo, ferramentas |
| `agent/core/mcp_hub.py` | Cliente MCP (stdio/HTTP) numa thread asyncio; importação de configs do Claude/Cursor |
| `agent/core/skills.py` | Skills no padrão `SKILL.md` + plugins (`plugins/<nome>/skills`, `.mcp.json`) |
| `agent/core/usage.py` | Medidor de tokens (`data/usage.json`) e políticas de economia |
| `agent/core/brain.py` | Fachada: liga tudo, seleção de perfil/modelo, modos texto/voz |
| `agent/gui.py` | Janela (QWebEngine), ponte `Api` (QWebChannel) com a página, worker do agente, bandeja e notificações |
| `agent/ui/web/` | Interface: `index.html`, `app.css` (design system "Órbita"), `app.js` (sem dependências externas), `logo.svg` |
| `agent/ui/render.py` | Markdown → HTML **sanitizado** (sem HTML cru, sem `javascript:`) e texto para a voz |
| `agent/ui/brand.py` | Nome, ícone (.ico gerado do SVG) e registro do app na barra de tarefas |
| `agent/core/routing.py` | Catálogo de capacidades (`data/model_catalog.json`) e escolha do melhor modelo por especialidade |
| `agent/core/conversations.py` | Conversas salvas (`data/conversations/`) e conversão para blocos da interface |
| `agent/memory/memory_manager.py` | Histórico diário e fatos de longo prazo |
| `agent/voice/` | Microfone (faster-whisper + Silero VAD), voz (Kokoro/Piper/Windows), atalho |

## Decisões importantes

- **Formato interno único de mensagens** (ver docstring de `providers.py`). Cada provedor converte na
  hora de enviar; o Claude recebe de volta seus blocos originais (`_native`) para preservar o raciocínio.
- **Ferramentas por prompt**: se o modelo não aceita tool-calling nativo, o loop injeta o catálogo no
  prompt e lê blocos `<tool_call>`; qualquer modelo vira agente.
- **MCP adiado**: servidores com muitas ferramentas (REA: 207) não entram no contexto; o modelo usa
  `find_tools`. `always_load` define um "kit inicial" sempre visível.
- **Ferramentas MCP rodam em sequência** (têm estado no servidor); só leituras embutidas rodam em paralelo.
- **Permissões por risco**: `read` nunca pergunta; `write` pergunta no modo *perguntar*; `exec` pergunta
  nos modos *perguntar* e *auto*; *livre* nunca pergunta.
- **Economia**: resultados antigos de ferramentas são encurtados, turnos velhos saem do contexto,
  saídas longas são cortadas e o freio pergunta antes de ultrapassar o orçamento por tarefa/dia.
- **Subagentes** compartilham o botão Parar e o orçamento do principal; profundidade máxima 2.

## Dados (pasta `data/`)

`settings.json` · `profiles/*.json` · `mcp.json` · `usage.json` · `model_catalog.json` · `conversations/` · `artifacts/` (imagens geradas/MCP) ·
`screenshots/` · `logs/agent.log` e `logs/mcp-<servidor>.log`
