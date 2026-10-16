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
- [ ] ⭐ "Descobrir o melhor agente": o Pesquisador consulta a web/benchmarks e sugere o modelo/servidor MCP ideal para uma tarefa, oferecendo configurar
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
- [ ] Sandbox opcional para o shell; lista de comandos proibidos
- [ ] Empacotar como `.exe` (PyInstaller) com instalador

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
- [x] Versionamento SemVer alfa (`agent/__init__.py`, `CHANGELOG.md`, regras no AGENTS.md); versão atual 0.1.0-alpha
- [x] Prompt padrão para evoluir o projeto com qualquer IA (`docs/PROMPT_EVOLUCAO.md`)
- [ ] Integração contínua no GitHub (rodar pyflakes + pytest a cada envio)
- [ ] Renomear pasta/arquivos `.bat` para Órbita (mantidos por compatibilidade por enquanto)
- [ ] Sons sutis de notificação; animação do logo enquanto trabalha

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
