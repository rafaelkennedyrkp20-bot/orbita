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
| `agent/core/grok_cli.py` | Grok Build (xAI) com a conta do usuário: login/estado do CLI oficial e provedor "agente externo" (`grok -p --resume`) |
| `agent/core/grok_bridge.py` | Ponte MCP "orbita" para o Grok Build: com ele como principal, chama a equipe (`delegate_task`), skills, ferramentas de criação e `check_web_page` do Órbita, com as permissões de sempre |
| `agent/core/agent_loop.py` | `AgentSession`: loop, permissões, contexto, freio de tokens, ferramentas por prompt, delegação |
| `agent/core/tools.py` | `Tool`, `ToolRegistry`, `ToolResult`, decorador `tool()`; busca de ferramentas adiadas |
| `agent/core/profiles.py` | Perfis/equipe (`data/profiles/*.json`): prompt de sistema, prompt inicial, modelo, ferramentas |
| `agent/core/mcp_hub.py` | Cliente MCP (stdio/HTTP) numa thread asyncio; importação de configs do Claude/Cursor |
| `agent/core/skills.py` | Skills `SKILL.md` + plugins. `when` vira roteador no prompt; `context: models` anexa a tabela só ao carregar |
| `agent/core/usage.py` | Medidor de tokens (`data/usage.json`) e políticas de economia |
| `agent/core/brain.py` | Fachada: liga tudo, seleção de perfil/modelo, modos texto/voz |
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
- **MCP adiado**: servidores com muitas ferramentas (REA: 207) não entram no contexto; o modelo usa
  `find_tools`. `always_load` define um "kit inicial" sempre visível.
- **Ferramentas MCP rodam em sequência** (têm estado no servidor); só leituras embutidas rodam em paralelo.
- **Permissões por risco**: `read` nunca pergunta; `write` pergunta no modo *perguntar*; `exec` pergunta
  nos modos *perguntar* e *auto*; *livre* nunca pergunta. Um caminho só (`_authorize`) para o loop, a ponte do
  Grok e a verificação da equipe; o perfil (grupos e `mcp_servers`) vale também para MCP chamado pelo nome.
- **Economia**: resultados antigos de ferramentas são encurtados, turnos velhos saem do contexto,
  saídas longas são cortadas e o freio pergunta antes de ultrapassar o orçamento por tarefa/dia. Se nem o turno
  atual cabe (modelo local), `_fit_turn` encurta o excesso e descarta passos antigos; skill carregada fica inteira.
  O teto é o menor entre o modo de economia e a janela do modelo (`capabilities.context_window`), até 1M. A
  compactação nunca desiste: modelo econômico, principal e, por fim, resumo extraído do histórico.
- **Subagentes** compartilham o botão Parar e o orçamento do principal; profundidade máxima 2.

## Dados (pasta `data/`)

`settings.json` · `profiles/*.json` · `mcp.json` · `usage.json` · `model_catalog.json` · `conversations/` · `artifacts/` (imagens geradas/MCP) ·
`screenshots/` · `logs/agent.log` e `logs/mcp-<servidor>.log`
