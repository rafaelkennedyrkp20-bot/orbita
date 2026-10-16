# ROADMAP — Evolução do Órbita (antigo AgentePessoal)

> **Leia isto antes de mexer no projeto.** Este arquivo é o guia de trabalho para qualquer IA
> (Claude, GPT, DeepSeek, Grok, Gemini...) ou pessoa que continue a evolução do agente.
>
> Regras para quem continuar:
> 1. Trabalhe **dentro do escopo** das tarefas abaixo. Ideia nova entra primeiro como `[ ]` na fase certa.
> 2. Ao concluir uma tarefa, troque `[ ]` por `[x]` e anote no **Diário** (data + quem + o que mudou).
> 3. Tarefa começada e não terminada: marque `[~]` e descreva no Diário onde parou.
> 4. Não quebre o que funciona: `venv\Scripts\python.exe -m pytest tests -q` deve passar antes de marcar `[x]`.
> 5. Arquitetura e convenções: [ARCHITECTURE.md](ARCHITECTURE.md) e [AGENTS.md](AGENTS.md).

Legenda: `[x]` feito e verificado · `[~]` parcial · `[ ]` pendente · ⭐ prioridade alta

---

## Fase 1 — Núcleo agêntico

- [x] Provedores multi-IA (`core/providers.py`): Ollama nativo, qualquer API compatível com OpenAI (OpenAI, DeepSeek, Gemini, OpenRouter, Groq, xAI, Mistral, LM Studio...) e Claude pelo SDK oficial
- [x] Loop agêntico com tool-calling nativo e streaming (`core/agent_loop.py`)
- [x] Ferramentas por prompt (`<tool_call>`) para modelos sem suporte nativo — automático
- [x] Recupera chamadas escritas como JSON no texto (modelos locais confusos)
- [x] "Empurrão" quando o modelo anuncia uma ação e para sem executar
- [x] Detector de loop: a mesma chamada falhando de novo recebe aviso para mudar de estratégia
- [x] Registro de ferramentas com JSON Schema e nível de risco (`core/tools.py`)
- [x] Ferramentas: arquivos (ler/escrever/editar/listar/glob com tamanhos/grep/mostrar), PowerShell, web, apps, screenshot com visão, mouse/teclado, clipboard, processos, volume, memória, skills, subagentes, MCP, imagem
- [x] Permissões `perguntar` / `auto` / `livre` + "sempre nesta conversa"
- [x] Contexto dentro do orçamento (encurta resultados antigos, descarta turnos velhos)
- [x] Memória de longo prazo (`remember`/`recall`) injetada no prompt
- [x] Lê `AGENTS.md` / `CLAUDE.md` da pasta de trabalho
- [x] Compactação inteligente: turnos antigos viram resumo (modelo econômico) ao passar de 85% do orçamento; se falhar, volta ao corte simples
- [ ] Contagem real de tokens por provedor (hoje: estimativa chars/3,5 quando a API não informa)
- [ ] Bloco de "raciocínio" recolhível na interface (hoje mostra só um resumo/contagem)
- [x] DeepSeek reasoner com ferramentas: `reasoning_content` preservado nas chamadas de ferramentas do turno ativo e podado em turnos antigos (`core/providers.py`, `core/agent_loop.py`)

## Fase 2 — Prompts de injeção, perfis e espaços de trabalho

- [x] Perfis em `data/profiles/*.json`: prompt de sistema (injeção), **prompt inicial** automático, provedor/modelo, temperatura, esforço (Claude), pasta de trabalho, ferramentas, servidores MCP
- [x] Vínculo modelo → perfil (escolher o modelo ativa o perfil vinculado)
- [x] Perfis prontos: Assistente Geral, Líder de Desenvolvimento, Programador, Revisor, Pesquisador, Designer, Grok Build, Engenharia Reversa, Automação do PC
- [x] Editor de perfis na interface
- [ ] Variáveis no prompt (`{workspace}`, `{user_name}`...) — hoje o ambiente é injetado automaticamente
- [ ] Importar/exportar perfis; galeria de perfis prontos
- [ ] "Prompts rápidos" acessíveis por `/comando` na caixa de texto
- [x] Projeto de trabalho: abrir/criar pasta pela tela inicial, pelo topo e por Ctrl+K, com projetos recentes e pasta sugerida em Documentos
- [ ] Conversas ligadas ao projeto (filtrar a lista lateral pelo projeto aberto)

## Fase 3 — MCP, Skills, Plugins e contas

- [x] Cliente MCP stdio + HTTP em thread própria; `data/mcp.json` no formato padrão `mcpServers`
- [x] **REA conectado** (`npx -y rea-agents@6.5.0 mcp`, 207 ferramentas) — testado: `open_binary` no notepad.exe → PE x86_64
- [x] Ferramentas MCP sob demanda (`find_tools` por palavra-chave ou nome) + `always_load` (kit inicial)
- [x] `inherit_env`: repassa só as variáveis pedidas (ex.: `GHIDRA_INSTALL_DIR`) sem vazar chaves
- [x] Ferramentas MCP executam em ordem (têm estado); só leituras embutidas rodam em paralelo
- [x] Skills `SKILL.md` (projeto, plugins, `~/.claude`, `~/.agents`, `~/.codex`), carregamento progressivo
- [x] Plugins `plugins/<nome>/` com `skills/` e `.mcp.json`
- [x] Importar servidores do Claude Desktop / Claude Code / Cursor; painel MCP com liga/desliga
- [x] ⭐ **Grok Build com a conta xAI** (`core/grok_cli.py`): login pelo navegador/código, provedor selecionável, membro da equipe, sessão retomada entre turnos, custo no medidor — testado com a conta real
- [ ] REA com decompilação nativa: instalar Ghidra 12.1 e definir `GHIDRA_INSTALL_DIR` (ação do usuário; ver README)
- [ ] Grok Build via ACP (`grok agent stdio`) para repassar pedidos de permissão do Grok à nossa interface
- [ ] Recursos e prompts MCP (`resources/list`, `prompts/list`); OAuth para servidores MCP remotos
- [ ] Catálogo navegável de servidores MCP (registro oficial) com instalação por clique
- [ ] Hooks antes/depois de ferramentas

### Integrações de programas (adicionar em `data/mcp.json`)
- [x] Exemplos prontos (desligados): Playwright (navegador), Windows-MCP, filesystem
- [ ] Photoshop / Adobe, Blender, Figma, Obsidian, Office: pesquisar servidores MCP confiáveis e testar

## Fase 4 — Equipe de agentes e orquestração

- [x] `delegate_task`: subagentes com contexto próprio, em paralelo, **cada um com seu perfil e modelo/API** — testado com Qwen3.8 27B local (2 programadores em paralelo, resultado integrado)
- [x] Perfil Líder de Desenvolvimento: planeja → delega em paralelo → revisa → testa
- [x] Lista da equipe e dos modelos com acesso vai no prompt do agente principal
- [x] Subagentes compartilham botão Parar e orçamento de tokens; profundidade máxima 2
- [x] Roteamento automático por especialidade (`core/routing.py` + `data/model_catalog.json`): notas por especialidade e custo; escolha muda com o modo de economia e só usa modelos com acesso; tabela de capacidades vai no prompt do principal; `generate_image` escolhe o modelo de imagem sozinho
- [x] Roteador de skills (`when` no frontmatter), handoff que exige Status DONE e resultado aprovado na Verificação (PARTIAL/BLOCKED não é entrega) e subagente que não redelega
- [ ] Vincular `DONE` ao resultado real de `verify_project` quando `verify=True`; hoje o parser também aceita o resultado positivo autodeclarado no texto do handoff
- [~] ⭐ "Descobrir o melhor agente": o Pesquisador consulta a web/benchmarks e sugere o modelo/servidor MCP ideal para uma tarefa, oferecendo configurar. Feito: skill `descobrir-agente` carregada sob demanda (tabela de modelos só ao carregar; não configura). Falta: configurar após confirmação (item abaixo)
- [ ] Configurar modelo/servidor MCP sugerido após confirmação explícita do usuário (exige decisão: muda configuração e MCP executa código)
- [ ] Revisão cruzada automática: ao terminar código, um segundo modelo revisa antes de entregar (opcional por perfil)
- [ ] Tarefas agendadas e fila em segundo plano com notificação na bandeja

## Fase 5 — Interface

- [x] Streaming, Markdown, código com destaque, tabelas, cartões de ferramentas e subagentes
- [x] Barra lateral: perfil, provedor/modelo (lista buscada no provedor), permissões, economia, voz, equipe, MCP, skills, tokens do dia
- [x] Painel direito: atividade detalhada + visualização de imagens/arquivos
- [x] Botão Parar (Esc), atalhos, anexar/arrastar imagens, ícone próprio, diálogos de perfil/configurações/histórico/permissão
- [x] Configurações: chaves de API (.env), conta Grok, modelo de imagem, modelo econômico, orçamentos, novo provedor
- [x] Métricas de GPU em thread separada
- [~] `generate_image` (OpenAI / OpenRouter / compatíveis) — implementado, **não testado** com chave real
- [x] Conversas salvas e reabríveis (`core/conversations.py`), lista lateral com busca, grupos por dia, renomear e apagar
- [x] Interface nova em motor web (QWebEngine) com tema escuro/claro
- [ ] Renderizar diagramas Mermaid e páginas HTML ("artefatos") no painel Visualizar
- [x] Ícone na bandeja do sistema com menu e notificações do Windows
- [ ] Atalho global de teclado para chamar a janela
- [x] Pontos de restauração por resposta: git "sombra" em `data/checkpoints` (sem tocar no git do projeto), cartão com arquivos alterados, diff colorido, Desfazer e Refazer (`agent/core/checkpoints.py`)
- [x] `@arquivo` no campo de mensagem: autocompletar com arquivos do projeto e conteúdo citado anexado à mensagem (economiza uma rodada de ferramenta) (`agent/core/mentions.py`)
- [x] Modo plano (Plan/Act): botão Planejar; ferramentas que alteram ficam bloqueadas no turno; botões Executar plano / Ajustar
- [x] Dica de conversa longa: sugere conversa nova para assunto novo (menos deriva e menos tokens)
- [x] ⭐ Desbloquear confirmação pendente (`AgentWorker.approve`) ao fechar o modal com `Esc` ou clicar em `Parar` (`agent/gui.py`, `agent/ui/web/app.js`)
- [ ] ⭐ Painel na interface para listar, editar e apagar memórias salvas por `remember` (`agent/memory/memory_manager.py`, `agent/ui/web`)
- [x] Conversas: menu próprio no botão direito (Renomear na linha, Apagar com confirmação) e "Renomear" no Ctrl+K
- [x] Prompt fixo por conversa (`pinned_prompt`, salvo na conversa, injetado como "## Instruções fixas desta conversa")
- [x] Busca de modelos (sem acento/maiúscula, por partes, contagem, setas + Enter) em Configurações › Modelos e no editor de perfil

## Fase 6 — Economia de tokens

- [x] Modos Economia máxima / Equilibrado / Livre (contexto, tamanho de saídas, passos)
- [x] Medidor por provedor:modelo em `data/usage.json` (nuvem × local) + custo do Grok
- [x] Freio: orçamento por tarefa e diário — o agente pausa e pergunta
- [x] Modelo econômico para subagentes; MCP adiado; skill não é recarregada no mesmo pedido
- [ ] Cache de prompt explícito por provedor e relatório de economia (quanto foi poupado)
- [ ] Limite de gasto em US$ por dia (hoje é em tokens)

## Fase 7 — Refino e qualidade

- [x] `LLM_KEEP_ALIVE=0` recarregava o modelo a cada chamada → `keep_alive` configurável (10 min)
- [x] `open_application` sempre dizia "sucesso" e usava `shell=True` com texto do usuário → corrigido (+ atalhos do Menu Iniciar)
- [x] `type_text` não digitava acentos → cola via clipboard
- [x] PowerShell: cores ANSI removidas, `&` automático para caminho entre aspas, `cwd` inválido tratado
- [x] Arquivos ANSI/cp1252 lidos corretamente; edição preserva codificação e `\r\n`
- [x] Busca web: parágrafos duplicados removidos; nova ferramenta `fetch_url`
- [x] Imports pesados (Whisper, teclado, pyautogui) só quando usados
- [x] Código morto removido (`llm_interface.py`, `file_ops.py`, roteador por palavras-chave, métodos sem uso)
- [x] 60 testes automatizados (`tests/`), incluindo servidor MCP real, agente externo, roteamento, compactação, contratos de entrega, `verify_project`, projetos e API manual
- [x] Log diário só em JSONL (uma linha por interação, sem reescrever o arquivo); lê o JSON antigo do dia se existir
- [x] Cancelamento em meio a chamada de ferramenta não grava `tool_calls` órfãos no histórico; `_TagFilter` faz `flush()` de `<` residual no fim do stream; links `file:` vindos de Markdown externo bloqueados (`agent/core/agent_loop.py`, `agent/ui/render.py`)
- [x] Otimização de velocidade medida (`scripts/medir_velocidade.py`, `tests/test_performance.py`): import preguiçoso de `httpx`, `asyncio` e `image_gen`; cliente HTTP compartilhado; cache de catálogo, provedores, credenciais do Grok CLI, conversas (`os.scandir`) e `platform.uname` no Windows (inicialização 159,04 ms → 95,54 ms, TTFT 853,69 ms → 28,12 ms, custo por turno 116,42 ms → 5,97 ms)
- [ ] ⭐ Mover memória e logs diários de `agent/memory/{daily_logs,long_term}` para `data/` (migrando arquivos existentes) e remover o `USER_PROFILE` morto (`agent/memory/memory_manager.py`, `agent/core/config.py`)
- [ ] Sandbox opcional para o shell; lista de comandos proibidos
- [ ] Empacotar como `.exe` (PyInstaller) com instalador
- [ ] Avaliar casca Tauri (Rust) reaproveitando `agent/ui/web`, para distribuir um `.exe` leve (baixa prioridade; o motor continua em Python)

---

## Fase 8 — Identidade e produto

- [x] Nome **Órbita** ("seu agente pessoal de IA"), logo próprio (estrela em órbita, degradê ciano→índigo→magenta)
- [x] Ícone em todas as janelas, na barra de tarefas (AppUserModelID próprio) e `.ico` multi-tamanho gerado do SVG
- [x] Atalhos "Órbita" na Área de Trabalho e no Menu Iniciar, abrindo sem console (`launcher.py --shortcut`)
- [x] Janela abre maximizada
- [x] Interface reescrita (`agent/ui/web`): trilho de navegação, páginas Chat / Equipe e perfis / Conexões / Configurações, passos recolhíveis, cartões de subagentes, indicador "trabalhando" com status ao vivo, notificações animadas, paleta de comandos (Ctrl+K), modais de permissão, lightbox de imagens
- [x] Configurações como página: Geral, Modelos (troca de modelo, modelos locais com baixar via Ollama, roteamento), Chaves, Conta Grok, Economia (uso do dia), Permissões, Voz, Sobre
- [x] Assistente de primeira execução (nome, IA local/nuvem/Grok, pasta de trabalho, permissões, voz)
- [x] Segurança da interface: HTML do modelo sanitizado, CSP restrita, navegação externa sempre no navegador do sistema
- [x] `.gitignore` para publicar sem modelos, chaves ou dados pessoais
- [x] Licença **GNU GPL v3** (`LICENSE`, aviso no README e em Configurações › Sobre) — melhorias distribuídas continuam abertas
- [x] Publicado no GitHub (rafaelkennedyrkp20-bot/orbita), só código-fonte
- [x] Roda no Linux: `iniciar_orbita.sh`, atalho `.desktop`, shell bash no `run_shell` (mata o grupo de processos no timeout), abrir programas por `.desktop`/`xdg-open`, volume por `pactl`/`amixer`, controle de tela sem derrubar o resto quando não há sessão gráfica, login/instalação do Grok em terminal do sistema, prompt com o SO real; testado em contêiner Debian + Python 3.12
- [x] Aviso de atualização e atualização com um clique usando o GitHub como âncora: git (`pull --ff-only`, recusa com alteração local) ou ZIP (substitui só o programa, cópia de segurança, manifesto para remoções); dados nunca tocados (`agent/core/updater.py`)
- [x] Versionamento SemVer alfa (`agent/__init__.py`, `CHANGELOG.md`, regras no AGENTS.md); versão atual 0.2.0-alpha
- [x] Prompt padrão para evoluir o projeto com qualquer IA (`docs/PROMPT_EVOLUCAO.md`)
- [ ] Integração contínua no GitHub (rodar pyflakes + pytest a cada envio)
- [ ] Renomear pasta/arquivos `.bat` para Órbita (mantidos por compatibilidade por enquanto)
- [ ] Sons sutis de notificação; animação do logo enquanto trabalha

## Fase 9 — Ferramentas de criação e o que os usuários mais pedem (pesquisa 2026-10-16)

> Fontes: discussões de usuários de agentes pessoais (memória persistente é o pedido nº 1; controle de programas é a
> maior lacuna; local-first com permissões por escopo é o mais elogiado) e de quem faz jogos com IA (Blender gera os
> assets 3D, Godot monta o jogo; ImageMagick é o padrão de edição de imagem por linha de comando).

- [x] ⭐ **Caixa de ferramentas opcional** (Opus/Antigravity + Claude): catálogo de programas que a IA sabe usar, baixados
  só quando a pessoa (ou o agente, com permissão) quiser, de URL oficial fixa com SHA-256, para `models/tools/`:
  ImageMagick (imagem), Blender (3D, modo sem janela por script Python), OpenSCAD (3D por código, leve), Godot (jogos),
  FFmpeg (vídeo/áudio). Página na interface com tamanho, status e instalar/remover; ferramenta do agente para listar e
  pedir instalação; nada entra no `requirements.txt`
- [x] ⭐ **Skills de criação** junto com a caixa (Claude): `editar-imagem`, `modelagem-3d`, `jogos-godot`,
  `jogos-web` (Canvas/Three.js, sem instalar nada) e `video-ffmpeg`, cada uma com fluxo testável e exemplos
- [ ] ⭐ Memória por projeto: o agente lembra sozinho decisões e estado de cada pasta de projeto entre conversas
  (junto com o painel de memórias já listado na Fase 5)
- [ ] ⭐ Tarefas agendadas/recorrentes ("todo dia às 9h, resuma meus e-mails"), com histórico e pausa
- [ ] Permissões por pasta: liberar escrita só no projeto aberto e leitura no resto, configurável
- [ ] Servidores MCP populares com um clique (Playwright, GitHub, Blender MCP, Godot MCP), com explicação do que fazem
- [ ] Perguntar antes da compactação automática (hoje compacta e avisa), com opção "sempre automático"
- [x] Equipe com modelos reais: DeepSeek, GLM e Nemotron testados, custo medido por rodada (Diário 2026-10-16)

## Diário

- **2026-10-15 — Claude (Opus 5.5)**: diagnóstico completo; criação do ROADMAP, ARCHITECTURE e AGENTS.md;
  núcleo agêntico novo (provedores, ferramentas, permissões, contexto, economia), perfis com prompts de
  injeção e prompt inicial, equipe de agentes com delegação paralela, MCP + REA, skills/plugins,
  integração com o Grok Build (conta xAI), nova interface, correções de desempenho/bugs e 38 testes.
  Testes reais: Qwen 14B (ferramentas: 162 s/53k tokens → 11 s/8,7k após correções), Qwen3.8 27B
  (delegação paralela correta), REA (abre binários; decompilação requer Ghidra), Grok Build (sessão retomada).
  Observação: o Qwen 14B se perde em tarefas longas; prefira o 27B local ou uma API na nuvem para trabalho agêntico.
- **2026-10-15 — Claude (Opus 5.5), parte 2**: roteamento automático por especialidade e compactação inteligente
  (com testes); conversas salvas/reabríveis; identidade **Órbita** (nome, logo, ícones, barra de tarefas, atalhos sem
  console, janela maximizada); interface reescrita em motor web com páginas, notificações, paleta de comandos,
  assistente de primeira execução e configurações completas. Nota de licença: o código pode ser MIT/Apache, mas
  distribuir um `.exe` com PyQt6 exige cumprir a GPL v3 do PyQt6 (ou trocar para PySide6, LGPL).
- **2026-10-15 — Claude (Opus 5.5)**: licença escolhida: GNU GPL v3 (copyleft; compatível com o PyQt6).
- **2026-10-15 — Gemini 4 Argon (Principal Architect Refinement)**: auditoria arquitetural e refinamento 2026:
  `AGENTS.md` reescrito com alta densidade, gates de verificação, fronteiras de módulos e protocolo de handoff;
  4 skills core criadas em `skills/` (`spec-plan-tdd`, `code-review-simplify`, `debug-recovery`, `creative-pipeline`);
  nova ferramenta `verify_project` (`risk="read"`) para Quality Gates determinísticos (`pyflakes` + `pytest`) sem atrito de permissão;
  contratos estruturados em `delegate_task` (`files`, `acceptance_criteria`, `verify`) com gate automático pós-subagente;
  suporte a `reasoning_content` no turno ativo para DeepSeek Reasoner com poda automática em turnos antigos;
  pipeline criativo em `generate_image` com `style` anchor, `negative_prompt`, `shot_id` e sidecar `.meta.json` + rota `xai:grok-2-image` e especialidade `video`;
  log diário append-only em `.jsonl` e 53 testes automatizados passando.
- **2026-10-16 — Claude (Opus 5.5)**: revisão do trabalho do Argon e do Grok (commitado antes, com crédito).
  Correções: `verify_project` executa código, então passou a `risk="exec"` (estava `read`, burlando permissões),
  usa o venv do próprio projeto, ignora venv/node_modules no lint e marca ferramenta ausente como "pulado";
  verificação automática da equipe roda uma vez só, depois de todos, pedindo permissão; skill de revisão citava
  parâmetro inexistente; log diário agora é só JSONL (o JSON inteiro ainda era reescrito a cada mensagem) e o
  código morto de histórico saiu; interface: compositor não some mais embaixo, topo cabe em telas menores,
  diálogo de projeto com botão fechar, projetos recentes e pasta sugerida em Documentos (antes sugeria a pasta
  Users do disco C:). AGENTS.md reescrito (desenvolvimento x uso, coordenação entre IAs, regras de versão),
  docs/PROMPT_EVOLUCAO.md, CHANGELOG e versão 0.1.0-alpha. Verificado: pyflakes 0 avisos, 60 testes,
  fluxo de criar/abrir projeto testado na janela real.
- **2026-10-16 — Claude (Haiku 5.5)**: item ⭐ "Descobrir o melhor agente" (escolhido por ser o único ⭐ pendente).
  Agentes de pesquisa recebem o protocolo `DISCOVERY_PROMPT` e a tabela de modelos com acesso no prompt de sistema
  (injetado em código, porque perfis já existentes não são sobrescritos). Não configura nada sozinho: a configuração
  automática ficou como item `[ ]`. Verificado: pyflakes 0 avisos; pytest 62 passando (60 anteriores + 2 novos:
  protocolo e tabela presentes no Pesquisador; ausentes no Assistente Geral). Não testado com modelo real nem na
  interface (não há mudança visual).
- **2026-10-16 — Claude (Opus 5.5)**: conjunto de ícones próprio para os agentes (SVG em degradê, mesmo estilo do
  logo) substituindo os emojis em cartões, topo, menus, painel da equipe e editor (com seletor). Emojis de perfis
  já salvos são convertidos na exibição. Verificado na janela (capturas da equipe, menu e editor); 60 testes.
- **2026-10-16 — Claude (Haiku 5.5)**: refinamento de orquestração, sem feature nova. Roteador de skills pelo
  campo `when` (o corpo não entra mais no prompt fixo); `DISCOVERY_PROMPT` saiu do prompt de todo turno de pesquisa
  e virou a skill `descobrir-agente` (tabela de modelos só ao carregar; pesquisa não herda o índice inteiro).
  Handoff sem Status/Verificação, ou PARTIAL/BLOCKED, ganha nota de máquina e não conta como entrega. Subagente
  não redelega. Skill `spec-plan-tdd` citava `verify_cmd`, parâmetro que não existe. Vídeo da skill criativa só
  se `ffmpeg` estiver no PATH. AGENTS.md enxugado (59 → 48 linhas) com essas fronteiras. Verificado: pyflakes
  0 avisos; pytest 65 passando (62 anteriores + 3: roteador, tabela só na skill, nota de handoff). Não testado
  com modelo real.
- **2026-10-16 — Codex (GPT-6)**: revisão do handoff após `ee4b3f7`; reconhece também `[PASS]`, `passando` e
  contagens válidas como `65 passed, 0 failed`, sem aceitar verificação ausente ou falha não zero. Regressão
  demonstrada antes da correção. Verificado: pyflakes 0 avisos; pytest 75 passando na árvore atual (66 do projeto
  e 9 testes não rastreados de checkpoints/mentions, sem relação com o handoff). Sem teste com modelo real.
- **2026-10-16 — Gemini 4 Argon**: revisão geral dos 5 problemas de maior impacto real. Corrigidos os 3 pequenos e
  seguros: (1) cancelar turno após `tool_calls` não grava mais chamadas órfãs sem `role: "tool"` no histórico (que
  quebravam os turnos seguintes com HTTP 400 nas APIs) e aviso de limite de passos usa o prefixo `(Sistema:` para
  não virar bolha falsa ao reabrir conversa (`agent/core/agent_loop.py`); (2) `_TagFilter.flush()` emite o sufixo
  retido quando há `<` nos últimos 11 caracteres em modo `prompted_tools` (`agent/core/agent_loop.py`); (3) bloqueio
  de esquema `file:` em `render.markdown_html` para impedir abertura de executáveis locais via clique em link
  Markdown sem permissão `exec` (`agent/ui/render.py`). Os outros 2 (deadlock em `AgentWorker.approve` ao fechar
  modal com `Esc` ou clicar em `Parar`, e painel para gerenciar memórias + migrar `agent/memory/` para `data/` e
  remover `USER_PROFILE` morto) entraram como `⭐ [ ]` no ROADMAP. Verificado: pyflakes 0 avisos; pytest 81 passando
  (69 do projeto, incluindo 3 novos de regressão, + 12 da árvore em andamento).
- **2026-10-16 — Claude Opus 5.5**: usabilidade a partir de pesquisa do que usuários mais elogiam em agentes de código
  (checkpoints do Cline, /undo do Aider, Plan/Act, apontar arquivos em vez de deixar o modelo procurar, evitar deriva em
  conversas longas). Novo: pontos de restauração por resposta com diff/desfazer/refazer, `@arquivo` com autocompletar e
  anexo do conteúdo, modo plano com ferramentas de alteração bloqueadas no turno, dica de conversa longa. Corrigido o
  ⭐ do Argon: fechar a confirmação com `Esc` ou clicar em Parar responde "não" em vez de travar o agente. Área: só
  `agent/gui.py`, `agent/ui/web/*` e módulos novos (sem tocar no que Grok e Argon editavam). Verificado: pyflakes 0;
  pytest 81 passando na árvore atual (13 novos: checkpoints, mentions, gui_turns); janela real com captura (autocompletar, cartão,
  diff, desfazer, refazer, Esc na confirmação). Custo medido: 0,4–0,9 s por foto numa pasta real.
- **2026-10-16 — Claude Opus 5.5**: aviso de atualização e atualização com um clique (\gent/core/updater.py\,
  \gent/gui.py\, \gent/ui/web\). O GitHub é a âncora: verifica a cada 6 h; mudança só em documentação não incomoda;
  novidades agrupadas (Novidades/Correções/Desempenho/Interface) e lista do que será atualizado/removido. Modo git:
  \pull --ff-only\, recusa com alterações locais ou commits fora do GitHub. Modo ZIP: troca só o programa, cópia de
  segurança em \data/updates/backup-…\, remoção só do que veio de versão anterior (manifesto). Processo separado espera a
  janela fechar, aplica e reabre pelo launcher. AgnesRiber convidada como colaboradora (escrita) no GitHub. Verificado:
  pyflakes 0; pytest 88 na árvore atual (7 novos); ponta a ponta contra o GitHub real (instalação ZIP da 0.1.0-alpha →
  check 1,4 s → apply 0,7 s → idêntica ao main, \data/\ e \.env\ intactos; CLI separada esperando o processo);
  modo git na pasta de desenvolvimento corretamente sem atualização; janela real com captura (aviso, novidades, Sobre).
- **2026-10-16 — Gemini 4 Argon**: otimização de desempenho com `cProfile`, `python -X importtime`, benchmark
  (`scripts/medir_velocidade.py`) e 7 testes determinísticos (`tests/test_performance.py`). Mediana de 3 execuções
  ANTES → DEPOIS: (a) inicialização do motor (`import` + `Brain`): `159,04 ms → 95,54 ms` (`-39,9%`; `import` de
  `125,18 ms → 59,88 ms`, `-52,2%`); (b) tempo até 1º token do motor (TTFT): `853,69 ms → 28,12 ms` (`-96,7%`);
  (c) custo por turno (`system_prompt` + `routing` + `conversations` + `memória`): `116,42 ms → 5,97 ms` (`-94,9%`;
  `system_prompt` `53,03 ms → 2,69 ms`, `routing` `57,09 ms → 1,21 ms`, `conversations` `7,70 ms → 2,14 ms`).
  Verificado: pyflakes 0 avisos; pytest 96 passando.
- **2026-10-16 — Claude Opus 5.5**: revisão do trabalho de velocidade do Argon (c8592bd): caches invalidados nas
  escritas, cliente HTTP compartilhado thread-safe e fechado no `finally`, ajuste do `platform` só no Windows — aceito
  sem mudanças. Portabilidade para Linux: `iniciar_orbita.sh` + `.gitattributes` (LF), launcher com `venv/bin/python`,
  aviso de `python3-venv` e atalho `.desktop`; `run_shell` em bash com descrição própria; `BASE_PROMPT` com o SO e o
  terminal reais (sem `platform.system()` na importação); `open_apps` por `.desktop`/`xdg-open`; volume por
  `pactl`/`amixer`; `pyautogui` sob demanda; disco `/`; Grok CLI com `install.sh` oficial num terminal do sistema;
  "Mostrar na pasta", atualizador e config do Claude Desktop nos caminhos do Linux. Verificado: Windows — pyflakes 0,
  pytest 99 + 2 pulados (só Linux); Linux (Docker, Debian, Python 3.12) — pyflakes 0, pytest 101 passando, janela real
  em Xvfb com captura (interface completa, shell = /usr/bin/bash) e `./iniciar_orbita.sh --check` do zero.
- **2026-10-16 — Claude Opus 5.5**: correção relatada pelo usuário — "3 modelos disponíveis" sem conseguir escolher.
  Causa: `<datalist>` só sugere opções que combinam com o texto do campo, e o campo tinha a chave de API (colada no
  Modelo da API manual, salva em `settings.json` como modelo e na lista do provedor). Correção: lista clicável com
  filtro, `looks_like_secret` (gui.py e app.js) recusando chave como modelo em todas as entradas e `scrub_secret_models`
  limpando configurações já salvas ao abrir. Verificado: pytest 111 + 2 pulados (12 novos); janela real com a
  configuração quebrada → aviso "Modelo corrigido", 3 modelos clicáveis, chave fora do `settings.json`.
- **2026-10-16 — Gemini 4 Argon → Claude Opus 5.5 (versão 0.2.0-alpha)**: conversas com menu próprio no botão direito
  (Renomear na linha com Enter/Esc, atualizando `#conv-title`; Apagar com `confirmBox`, abrindo conversa nova se era a
  aberta; `Api.deleteConversation` também zera o Brain), "Renomear conversa" e "Prompt da conversa" no Ctrl+K; prompt
  fixo por conversa (`Brain.pinned_prompt`/`set_pinned_prompt`, campo `pinned_prompt` no JSON, `Api.setPinnedPrompt`,
  selo e faixa no topo; em `agent_loop.py` só 2 linhas em `system_prompt`); busca de modelos compartilhada
  (`bindSearchableModels`) em Configurações › Modelos e no editor de perfil (sem `<datalist>`), mantendo `looksLikeKey`.
  `Api.push` ignora `RuntimeError` se a janela fechar com uma thread ainda respondendo. Verificado: pyflakes 0; pytest
  113 + 2 pulados (2 novos: renomear/apagar pela Api; prompt fixo salvo, limpo em conversa nova, reaplicado ao reabrir e
  presente/ausente no system prompt); janela real com `QWidget.grab` e `data/settings.json` restaurado (menu de
  contexto, renomear inline, Ctrl+K, apagar a conversa aberta, modal e selo do prompt, busca "CLÁUDE son" → 1 de 6 e
  Enter aplicando o modelo, busca "deepseek r1" no editor de perfil).
- **2026-10-16 — Claude Opus 5.5**: correção da tela relatada pelo usuário (barra de input sumindo e Ao vivo "bugando").
  Causa medida na janela real: `#side` sem `min-height:0` fazia a linha da grade crescer com o feed (composer em
  y=1243 numa janela de 940) e a coluna `1fr` da resposta esticava até 6.357 px com uma linha longa. Correção:
  `minmax(0,…)` na grade e na resposta, `min-height:0` no painel. Revisão do trabalho não commitado de outra IA (prompt
  do usuário): mantidos o bloco de raciocínio (reescrito com texto completo, tempo e fechamento automático via evento
  `reasoning_end`) e o Ao vivo com tipos; desfeitos o botão de ocultar a barra (sumia junto com ela) e a renomeação
  `#composer` → `#composer-footer` (quebrava o layout); compactação manual refeita no worker (antes chamava o modelo
  na thread da UI e não fazia nada abaixo de 85%) com `_maybe_compact(force=True)` e resumo estruturado. Arquivos
  avulsos da outra IA (`test_improvements.py`, `MELHORIAS_*.md`, `RESUMO_*.md`) retirados do repositório.
  Verificado: pytest 115 + 2 pulados (2 novos de compactação); janela real: composer visível (817–922 de 940),
  overflow horizontal 0, raciocínio 1.320 caracteres aberto → fechado ao escrever.
- **2026-10-16 — Claude Opus 5.5**: pedido do usuário — ditado no microfone, mais liberdade para os modelos e
  equipe que não troque para modelo local sozinha. Diagnóstico da voz: a gravação antiga cancelava após 5 s sem
  detectar fala, sem aviso, e mesmo funcionando enviava a mensagem e respondia falando. Novo `agent/voice/dictation.py`:
  grava até o 2º clique, parcial a cada ~1 s, final preciso. A pedido do usuário, nada pesado por padrão: com chave
  da Groq/OpenAI transcreve na nuvem (`/audio/transcriptions`, como ChatGPT/Claude — funciona em PC fraco; se a nuvem
  cair no fim, fica o último parcial); sem chave, Whisper leve neste PC (tiny no parcial, base ~150 MB no final).
  GPU e modelos maiores são opcionais (botão instala `nvidia-cublas-cu12`/`nvidia-cudnn-cu12`; aquecimento da GPU
  durante a fala; volta para a CPU se faltar cuBLAS). Equipe: `team_model` = "principal" (padrão) faz o ajudante usar
  o modelo do principal; roteador só em "auto". `agent/core/capabilities.py`: nível ponta/padrão/compacto ajusta
  prompt e passos (permissões não mudam). Verificado: pytest 139 + 2 pulados (24 novos); motor com fala real em pt-BR:
  CPU tiny parcial 0,6 s, base final 0,9 s; GPU small final 1,0 s, turbo parcial 0,5 s/final 0,8 s; janela real com
  microfone simulado tocando a frase: parciais desde ~4 s e final ~1 s após Concluir; telas Equipe e Voz capturadas.
  Não verificado: nuvem com chave real (o usuário não tem chave da Groq/OpenAI) — formato coberto por teste.
- **2026-10-16 — Claude Opus 5.5**: caso real do usuário (DeepSeek, site de jogos com 3 agentes): HTML e CSS feitos
  em paralelo usaram nomes diferentes (18 classes do HTML sem estilo, header não fixo); só o revisor percebeu no fim.
  Correção na causa: `delegate_task` ganhou `contract` (mesmo texto para todos os ajudantes) e o prompt da equipe manda
  definir o contrato — ou criar o esqueleto — antes de delegar partes que se encaixam; novo
  `agent/core/integration.py` compara classes/IDs entre HTML, CSS e JS alterados durante a delegação e anexa o que não
  bate ao resultado (CSS com variantes sem uso não conta sozinho; varredura limitada em profundidade/tempo). Verificado:
  pytest 143 + 2 pulados (4 novos, incluindo delegação real com 2 ajudantes escrevendo arquivos); no site do usuário já
  corrigido a checagem fica em silêncio; pasta do usuário inteira varrida em 0,24 s.
- **2026-10-16 — Claude Opus 5.5**: equipe sugerida pelo ambiente, para qualquer modelo. Novo `agent/core/teamwork.py`:
  estimativa do pedido (construção, escopo, partes listadas, contagem pedida, perguntas curtas excluídas) vira uma
  sugestão só daquele turno, no fim do prompt (o resto continua em cache), com nº de ajudantes e as 3 fases; modelos
  compactos só se a pessoa pedir. Paralelismo por nível/provedor (6/4/2; local = 2 por dividir a GPU), fila para o
  excedente, configurável (`team_max_parallel`). Ajudantes recebem a lista do que os colegas fazem. Verificado: pytest
  155 + 2 pulados (12 novos, incluindo prompt real de turno grande × pequeno); página Equipe capturada.
- **2026-10-16 — Claude Opus 5.5**: teste real autorizado pelo usuário, com a API do river (mesmo pedido: "loja de jogos
  indie completa em HTML/CSS/JS"). Rodada 1 (DeepSeek-V4.1-Flash, antes): o modelo seguiu o fluxo sugerido (esqueleto +
  `delegate_task` com 4 ajudantes e contrato de 1,1 mil caracteres) e o site ficou bom, mas: um ajudante subiu
  `http.server` e o `run_shell` travou 27 min (neto segurando o pipe; o kill não alcançava a árvore) e outro "testou"
  controlando a tela (6 screenshots, cliques) — 1,13 M tokens só ele, 2,41 M no total, 35 min. Correções: `taskkill /T`
  + `communicate` com prazo, `background=true` e detecção automática de servidores (`atexit` encerra);
  `check_web_page` (`agent/actions/web_check.py`, Chromium offscreen em processo separado, script assíncrono por
  consulta); ajudante genérico sem o grupo `pc`; teto `helper_token_cap` (300 mil) → PARTIAL; checagem de integração
  reconhece elementos criados pelo JS (`el.id =`, templates). Rodada 2 (GLM-5.3-Flash, depois): mesmo fluxo, 4
  ajudantes, `check_web_page` usado 21 vezes, nenhum controle de tela, 8,9 min e 1,16 M tokens (-52%); site com 0 erros
  de JS nas 4 páginas, sem overflow no celular, integração limpa. Verificado também: pytest 159 + 2 pulados.
- **2026-10-16 — Claude Opus 5.5 (Antigravity) + Claude Opus 5.5**: caixa de ferramentas da Fase 9. O Opus do
  Antigravity fez `agent/core/toolbox.py` (download só do catálogo e por https, tamanho e SHA-256 conferidos, `.part` e
  pasta temporária, zip/tar.xz com proteção contra caminhos perigosos, 7z pelo tar do Windows), o catálogo com versões
  fixas e hashes oficiais, `toolbox_list`/`toolbox_install` (risk "exec"), a ponte em `gui.py` e 10 testes — e parou
  pelo limite de uso. Concluído aqui: seção "Ferramentas de criação" (cartões, progresso, instalar/remover com
  confirmação), detalhe no modal de permissão, nomes das ferramentas, as 5 skills e o README. Verificado: pytest 175 +
  2 pulados; instalação real do ImageMagick (3 s) e do OpenSCAD (6 s) com hash conferido e teste do programa; o agente
  (Nemotron) fez um porta-copos 3D no OpenSCAD (STL + prévia) e a miniatura no ImageMagick em 42 s / 131 mil tokens;
  janela real com a seção e o pedido de permissão do Blender capturados.
- **2026-10-16 — Claude Opus 5.5**: relato de amigo do usuário — atualização não funcionava no Linux. Causas encontradas
  no código: (1) `brand.ensure_ico()` regravava o `app.ico` (versionado) quando o `.svg` parecia mais novo — datas
  aleatórias após `git clone` e bytes diferentes por plataforma deixavam o git sujo e o `apply_git` recusava;
  (2) `chmod +x` virava alteração no Linux; (3) pasta de outro usuário (sudo) falhava sem explicar e, no modo ZIP,
  podia gravar metade. Correções: ícone só gerado se faltar; `GENERATED` restaurado antes do pull e ignorado no status;
  `core.fileMode=false`; `write_problem()` no check, no apply e checagem de escrita antes de gravar o ZIP; aviso com
  quebra de linha. Verificado: pytest 177 + 2 pulados (2 novos: clone com remoto local e ícone regravado; pasta sem
  escrita). Não verificado num Linux real nesta rodada (Docker Desktop não subiu).
- **2026-10-16 — Claude Opus 5.5**: o amigo do usuário (Linux) continuava sem atualizar: "alterações locais em
  iniciar_orbita.sh e requirements.txt". Provável causa: Python 3.13 da distro (o script aceitava só 3.10–3.12) e o
  peso das dependências. Resolução das dependências para Linux com `uv pip compile` (sem instalar): `silero-vad` puxava
  torch 2.14 + 16 pacotes nvidia-* + triton (117 → 90 pacotes sem ele); 3.13 e 3.14 resolvem com wheels. Mudanças:
  `silero-vad` opcional; `.sh`/`.bat` aceitam 3.10–3.14; `apply_git(keep_local=True)` com backup + `git stash` +
  reaplicação (conflito: fica a versão nova, a do usuário no backup); `check` lista `local_changes` em vez de bloquear;
  botão "Atualizar guardando minhas alterações". Verificado: pytest 179 + 2 pulados (clone real com edição mantida e com
  conflito); janela de atualização capturada. Não verificado num Linux real (Docker Desktop não subiu).
