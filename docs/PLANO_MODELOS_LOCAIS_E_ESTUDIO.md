# Plano de evolução do Órbita — modelos locais e estúdio integrado

Data: 18/10/2026. Autor: Codex (GPT-6). Atualizado em 19/10/2026 por auditoria do código (issue #6, Claude Opus 5.5).

**Estado em 19/10/2026: em execução.** Dos 20 cartões, **7 feitos**, **13 parciais** e **0 pendentes**: todos já têm código; o que falta está na linha **Falta** de cada cartão (seção 7). Legenda: `[x]` feito, `[~]` parcial, `[ ]` pendente. "Feito" quer dizer código e testes automatizados que cobrem o aceite principal, conferidos no código e não só no ROADMAP. Nenhum cartão tem validação real registrada: o Diário das ondas 1 a 5 diz "janela real não aberta", e não há rodada real com Ollama, ComfyUI, voz ou o Actions do GitHub. Pela seção 10, essa validação continua pendente em todos.

## 1. Objetivo e limites

Transformar o suporte local que o Órbita já oferece em uma experiência acessível: encontrar uma IA no computador, escolher um modelo adequado, conversar e usar ferramentas sem configuração técnica desnecessária. Depois, ampliar documentos, programação, criação e continuidade de tarefas sobre a mesma base.

A entrega de planejamento (18/10) alterou só este documento e `ROADMAP.md`, sem código, dependências, configurações, licença, prompts, skills, versão ou dados pessoais. A implementação veio depois, nas ondas 1 a 5 do Diário de 19/10 (Grok 4.7). A auditoria de 19/10 alterou só este documento.

## 2. Base e método da análise

- Órbita: revisão a partir de `85c1e23`, com leitura de `ARCHITECTURE.md`, `ROADMAP.md`, provedores, configurações, loop, equipe, conversas, memória, GPU, geração de imagens, atualizador e fluxos da interface. A pasta `.claude/` já estava não rastreada e foi preservada.
- Referência: Locally Uncensored 3.0.6, commit [`961621610ba365160c99696edbc574c9bd5474f1`](https://github.com/PurpleDoubleD/locally-uncensored/tree/961621610ba365160c99696edbc574c9bd5474f1), obtido em cópia temporária fora do Órbita. As fontes abaixo estão fixadas nesse commit para permitir repetir a análise.
- Foram lidos implementação e exemplos de testes dos fluxos relevantes. A referência não foi instalada nem executada; não foram rodados seus instaladores, modelos ou testes. Presença de código/teste não comprova desempenho ou correção em uso. Declarações do README são tratadas como declarações do autor.
- Prioridades, estimativas e desenho proposto são avaliação para o Órbita. Não são resultados de benchmark. Não foi feita auditoria integral dos dois repositórios.

## 3. Conclusão arquitetural

O maior ganho está no gerenciamento da experiência local, não na quantidade de provedores. O Órbita já combina Ollama, APIs compatíveis, modelos por perfil, equipe, MCP, voz, memória e pontos de restauração. A referência organiza recursos semelhantes como produto: descoberta de motores, catálogo orientado por hardware, downloads, diagnóstico, documentos e criação no mesmo fluxo.

Manter Python + PyQt6/QWebEngine e estender os contratos atuais é a proposta inicial. A referência usa Tauri/Rust + React/TypeScript, o que torna uma transposição direta cara. A troca de casca já prevista na Fase 7 continua de baixa prioridade e precisa de medição própria; ela não é pré-requisito para nenhuma entrega abaixo.

Um servidor gerenciado de `llama.cpp` é uma possibilidade posterior a Ollama/LM Studio, não o primeiro passo. A implementação da referência administra processo, porta real, saúde, modelo GGUF, projetor de visão e contexto; isso é muito mais do que adicionar uma URL ao catálogo. Fonte: [cliente do motor](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/engine.ts).

## 4. Reaproveitamento e licenças

O Órbita declara GPL v3. A referência declara **AGPL-3.0-only**, não uma licença permissiva sem condições. O plano inicial é reimplementar comportamentos adequados nos módulos do Órbita, com referências de procedência, sem transplantar código ou ativos. Fontes: [LICENSE da referência](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/LICENSE) e [package.json](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/package.json).

Se uma tarefa justificar incorporar código, primeiro registrar arquivos/trechos, autores, avisos, dependências e obrigações da distribuição. GPLv3 e AGPLv3 permitem determinadas combinações, mas isso não permite retirar a AGPL do material recebido; a interação remota acrescenta obrigações a avaliar na combinação. Não é motivo para descartar a referência nem para mudar automaticamente a licença do Órbita. Fonte: [orientação da GNU sobre compatibilidade](https://www.gnu.org/licenses/license-compatibility.en.html).

Licença do aplicativo não cobre automaticamente pesos, LoRAs, vozes, executáveis e custom nodes. Cada item de catálogo deverá registrar origem, versão/revisão e licença próprios, inclusive limitações de redistribuição e uso. Nenhum peso será incluído no Git. Qualquer decisão de incorporar código ou redistribuir componentes entra na tarefa correspondente antes da publicação.

## 5. Comparação funcional

A coluna "Estado encontrado" é a foto de 18/10, antes da implementação. O estado atual de cada lacuna está nos cartões da seção 7.

| Área | Evidência na referência | Estado encontrado no Órbita | Decisão |
|---|---|---|---|
| Modelos locais | Descoberta de motores e motor gerenciado | Ollama nativo, LM Studio e API manual compatível | Melhorar descoberta e ciclo de vida; não recriar provedores |
| Hardware | Recomendação e classificação de capacidade | Métricas NVIDIA; contexto/keep-alive ajustáveis | Acrescentar recomendação honesta e diagnóstico |
| Instalação de modelos | Catálogo, arquivos auxiliares e downloads verificados | `pullModel` do Ollama com progresso básico | Evoluir gerenciamento e cancelamento |
| Uso local privado | Separação entre fluxos locais e cloud, com exceções documentadas | Provedores e ferramentas locais/remotos coexistem | Tornar destino dos dados explícito e criar política local |
| Concorrência | Fila local e coordenação de VRAM | Equipe paralela com limites por modelo/provedor | Coordenar recursos compartilhados e preservar concorrência útil |
| Avaliação | Comparação e benchmark com velocidade e correção | Scripts de velocidade do programa e catálogo de capacidades | Medir modelos no hardware do usuário |
| Memória | Escopo, origem, orçamento e edição | Fatos e logs globais; painel/projeto pendentes | Consolidar painel, migração e isolamento por projeto |
| Documentos | Extração, fragmentação e busca por embeddings | Leitura de arquivos; anexos não imagem viram caminhos no campo de texto | Criar biblioteca documental com fontes |
| Conversas longas | Resumo estruturado e orçamento | Compactação já implementada | Refinar preservação e medição; não refazer |
| Programação | Mapa do repositório e alterações pendentes para revisão | Busca, edição, Plan/Act, diff após execução e desfazer/refazer | Acrescentar revisão antes da gravação e seleção de contexto |
| Segundo plano | Estados e cancelamento de tarefas/processos | Subagentes vinculados ao turno; fila durável/agendamento pendentes | Separar tarefa durável de simples delegação |
| Criação | Integração ComfyUI e fluxos de mídia | Imagem via APIs; toolbox com Blender/ImageMagick/FFmpeg/Godot | ComfyUI opcional e integrado à toolbox |
| Artefatos | Galeria e reutilização | Painel de imagens e cartão de arquivos do turno | Evoluir para biblioteca persistente |
| Portabilidade | Importação e exportação de conversas | Histórico local, sem fluxo equivalente identificado | Exportação própria primeiro, importadores depois |
| Voz | Turnos interrompíveis; referência declara beta em inglês | Whisper, Kokoro/Piper/Windows e ditado em português | Melhorar interrupção e latência preservando PT-BR |
| Controle do PC | Consentimento por conversa, pausa e restrições por aplicação | Mouse/teclado/screenshot e permissões por risco | Evoluir escopo e interrupção, sem reduzir risco |
| Distribuição | Builds e canal de atualização assinado | Git/ZIP com backup; CI/instalador pendentes | Consolidar CI, empacotamento e autenticidade |
| API e celular | API local autenticada e acesso remoto opcional | Ponte específica para Grok, sem serviço geral equivalente | Avaliar por último, com contratos distintos |

Há também divergência documental: `app.js` já tem `thought()`/`endThought()` com `<details>` recolhível (texto completo, tempo, fecha ao terminar via `reasoning_end`), mas a Fase 1 ainda lista esse bloco como ausente. Não é funcionalidade nova. O Diário de 16/10 registra a conferência na janela real ("raciocínio 1.320 caracteres aberto → fechado ao escrever"), então o item da Fase 1 e o de reconciliação da Fase 10 podem ser fechados no ROADMAP. O mesmo cuidado vale para Plan/Act, compactação, MCP, voz e checkpoints, que já existem.

## 6. Ordem de execução

P0 = primeira entrega; P1 = próxima expansão; P2 = após estabilizar as bases; P3 = avaliar conforme demanda. Esforço relativo: S = pequeno, M = médio, G = grande, GG = várias entregas. Os tamanhos incluem testes e integração; não são promessa de prazo.

| Onda | Entregas | Resultado observável para o usuário | Estado em 19/10 |
|---|---|---|---|
| 1 — Modelos locais | LU-01 → LU-02/LU-03 → LU-04 | Encontra o motor, escolhe um modelo informado, acompanha/cancela download e entende quais dados saem do computador | LU-01 `[x]`; LU-02, LU-03, LU-04 `[~]` |
| 2 — Qualidade e contexto | LU-05 → LU-06; LU-07 → LU-08; início de LU-17 | Menos disputa pela GPU, escolhas medidas, memória por projeto e perguntas a documentos com fontes | LU-07, LU-08 `[x]`; LU-05, LU-06 `[~]` |
| 3 — Desenvolvimento e continuidade | LU-09, LU-10, LU-11, LU-15; conclusão do escopo de LU-17 | Revê alterações antes de aplicar, usa projetos grandes e retoma tarefas/conversas | LU-10, LU-15 `[x]`; LU-09, LU-11, LU-17 `[~]` |
| 4 — Criação e voz | LU-12 → LU-13 → LU-14; LU-16 | Cria imagens locais, encontra e reutiliza resultados, depois amplia vídeo/áudio e conversa por voz | LU-16 `[x]`; LU-12, LU-13, LU-14 `[~]` |
| 5 — Distribuição e integrações | LU-18 (CI inicia já na onda 1), LU-19 → LU-20 | Instala/atualiza com confiança e, se houver demanda, acessa por outros clientes | LU-19 `[x]`; LU-18, LU-20 `[~]` |

As ondas indicam dependências e foco, não um pacote único. Cada cartão é executado em sessão própria; cartões grandes são divididos nos passos abaixo. Todas as ondas foram iniciadas em 19/10 (versão 0.3.0-alpha); o que resta de cada cartão está na linha **Falta**.

## 7. Backlog executável

Cada cartão começa com o estado auditado em 19/10: evidência no código (`arquivo:símbolo`), testes que a cobrem e o que falta. O texto do plano abaixo dela continua valendo para o que falta.

### LU-01 — Encontrar e diagnosticar motores locais · P0 · M · `[x]`

- **Estado:** feito. `agent/core/local_engines.py:probe_engine`/`detect_local_engines` (só loopback, valida o JSON de `/api/tags` e `/models`, 401/403, limite de 64 KB e prazo, cancelamento, sem seguir redirecionamento); `agent/gui.py:discoverLocalEngines`/`cancelEngineDiscovery` em thread; `app.js:renderLocalEngines` (o modelo só muda com clique; sem motor, indica instalar Ollama ou LM Studio). Testes: `tests/test_local_engines.py`.

- **Entregar:** procurar primeiro Ollama e LM Studio em loopback, validar resposta compatível e mostrar acessível/sem modelo/incompatível/sem resposta. Reutilizar configuração manual e não trocar o provedor ativo silenciosamente. Outros motores compatíveis entram por configuração; ampliar a lista somente após teste de contrato.
- **Arquivos:** `agent/core/providers.py`, `agent/core/settings.py`, `agent/gui.py`, `agent/ui/web/app.js`; `tests/test_providers.py`, `tests/test_workspace_api.py`. Um módulo de descoberta só será extraído se o ciclo de vida exigir separação.
- **Dependências:** nenhuma. **Aceite:** serviços simulados cobrindo 200 válido, 200 não compatível, 401 e conexão pendurada; sondas com prazo e cancelamento, UI responsiva; endpoint personalizado e seleção existente preservados. Máquina sem motor mostra caminho de instalação, sem instalar sozinha.
- **Inspiração:** [backend-detector.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/backend-detector.ts). Sua sonda verifica HTTP; no Órbita, validar também o conteúdo para não identificar um serviço qualquer como IA.

### LU-02 — Catálogo orientado por hardware e capacidade · P0 · M · `[~]`

- **Estado:** parcial. `agent/core/local_catalog.py:model_recommendations` (confortável/apertado/não recomendado/desconhecido; KV e auxiliares; download separado do consumo; sem sensor = desconhecido) e `agent/core/local_models.json` (Qwen3 1.7B e 4B, Gemma 3 4B, com fonte, revisão e licença); `agent/actions/gpu_monitor.py:get_hardware_info`; `agent/gui.py:recommendLocalModels`; `app.js:renderLocalCatalog`. Testes: `tests/test_local_catalog.py`. **Falta:** validar os três modelos em PT-BR e com ferramentas (todos com `pt_br_validation: "not_tested"`); medição no hardware (hoje só estimativa); leitura de GPU AMD/Intel.

- **Entregar:** RAM, GPU/VRAM quando disponíveis, espaço livre, tamanho do download, quantização, contexto e capacidades verificadas. Exibir confortável/apertado/não recomendado/desconhecido; distinguir estimativa de medição. Começar por um catálogo pequeno de modelos de texto, visão e ferramentas testados em PT-BR, com licença e revisão das fontes.
- **Arquivos:** `agent/actions/gpu_monitor.py`, `agent/core/routing.py`, `agent/core/capabilities.py`, `agent/core/settings.py`, `agent/gui.py`, `agent/ui/web/app.js`; catálogo versionado proposto em `agent/core/local_models.json`; `tests/test_routing_compaction.py`, `tests/test_capabilities.py` e novos testes de catálogo/hardware se necessários.
- **Dependências:** LU-01. **Aceite:** cenários CPU sem GPU, GPU não identificada e memória insuficiente; tamanho do arquivo nunca apresentado como consumo total de VRAM; considerar contexto/KV cache e auxiliares de visão; ausência de sensor não impede uso. Modelo sem metadados recebe “desconhecido”, não selo positivo.
- **Inspiração:** [hardware.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/hardware.ts), [vram-fit.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/vram-fit.ts) e [model-bundles.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/model-bundles.ts). A regra de VRAM de mídia da referência é heurística; não transplantar suas constantes para LLMs.

### LU-03 — Gerenciador de modelos e downloads confiáveis · P0 · G · `[~]`

- **Estado:** parcial; (a) feita, (b) em parte. `agent/core/model_manager.py:ModelManager.start_pull`/`cancel`/`_load` (um job por modelo, cancelado nunca vira "pronto", `data/model_jobs.json` marca `interrupted` ao reabrir) e `ollama_action` (descarregar com `keep_alive: 0`, remover por `/api/delete`, com `confirmBox` no `app.js`); inventário em `agent/gui.py:localModels`. Testes: `tests/test_model_manager.py`. **Falta:** mostrar quais modelos estão carregados (`/api/ps`) e carregar sob pedido; (c) GGUF direto e (d) motor gerenciado não começaram.

- **Entregar em partes:** (a) enriquecer o pull Ollama com cancelamento, erros e inventário; (b) carregar/descarregar/remover com estado real e confirmação adequada; (c) somente se necessário, downloads diretos GGUF com retomada, integridade e arquivos auxiliares; (d) avaliar motor gerenciado depois da experiência com motores externos.
- **Arquivos:** `agent/gui.py` (`pullModel`), `agent/core/providers.py`, `agent/core/settings.py`, `agent/ui/web/app.js`; `tests/test_providers.py`, `tests/test_gui_turns.py`; módulo proposto `agent/core/model_manager.py` para jobs que excedam o papel da GUI. Reutilizar princípios de `agent/core/toolbox.py`, sem misturar seu catálogo de executáveis com pesos.
- **Dependências:** LU-01; usa LU-02 para recomendações. **Aceite:** cancelar sem falso “concluído”; reiniciar a UI sem perder identificação do job; dois pedidos do mesmo modelo não criam gravações concorrentes. Para download direto: `.part`, retomada quando suportada, tamanho exato e SHA-256 quando publicado, promoção atômica só após validação, erro em falta de disco/hash, bundle de visão incompleto não anunciado como pronto. Não remover arquivos de outra aplicação ao apenas desvincular.
- **Inspiração:** [download.rs](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src-tauri/src/commands/download.rs) e [model-bundles.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/model-bundles.ts). Não prometer “pausar/retomar” para todo backend: no Ollama, usar o contrato real do servidor.

### LU-04 — Política de execução local e destino dos dados · P0 · M · `[~]`

- **Estado:** parcial. `agent/core/local_policy.py:data_destination`/`refusal`/`tool_block` (gateway em localhost não ganha selo local); aplicada em `agent/core/providers.py:_coordinated_inference` (chat, resumo, equipe, avaliação), `agent/core/grok_cli.py`, `agent/actions/image_gen.py`, `agent/core/local_api.py:default_chat` e `agent/core/routing.py`; ditado forçado para local em `agent/gui.py`; `agent/core/agent_loop.py` bloqueia `run_shell`, `web_search`, `fetch_url` e MCP. Testes: `tests/test_local_policy.py`, `test_image_backend.py::test_local_only_still_refuses_the_cloud_image_api`, `test_local_api.py::test_default_chat_refuses_cloud_when_local_only`. **Falta:** indicar local/nuvem/indeterminado por operação; hoje só aparece "Modelo atual" em Configurações › Modelos.

- **Entregar:** seleção explícita “somente local” para os fluxos gerenciados, indicação local/nuvem/indeterminado por operação e impedimento de fallback silencioso para API paga. Aplicar a chat, resumo, equipe, memória/embeddings, visão, voz e geração. Endereço `localhost` de um gateway não prova que a inferência é local.
- **Arquivos:** `agent/core/settings.py`, `agent/core/providers.py`, `agent/core/routing.py`, `agent/core/agent_loop.py`, `agent/core/brain.py`, `agent/core/usage.py`, `agent/actions/image_gen.py`, `agent/ui/web/app.js`; testes de provedores/roteamento/loop.
- **Dependências:** LU-01; catálogo de LU-02. **Aceite:** mocks de rede negando saída externa confirmam que uma falha local não envia conversa à nuvem; automações auxiliares obedecem à mesma política; atualizações/busca/download ficam separados e explícitos. Servidor remoto declarado “local” e gateway desconhecido não recebem selo offline verificado. Shell/MCP/CLI externos só participam dessa promessa após controle verificável de saída; até lá, restringir esses caminhos no modo estrito e descrever o limite, sem prometer isolamento de sistema operacional inexistente.
- **Fonte comparativa:** [política e exceções declaradas no README](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/README.md). A referência informa consultas de atualização e eventos do botão Cloud; não assumir que “local” equivale a zero rede.

### LU-05 — Coordenar inferência e memória da GPU · P1 · G · `[~]`

- **Estado:** parcial. `agent/core/inference_queue.py:InferenceQueue`/`inference_resource` (FIFO por recurso, cancelamento ainda na fila, vaga liberada em exceção, `inference_resource` agrupa motores na mesma placa), usada em `agent/core/providers.py:_coordinated_inference`, `agent/voice/dictation.py`, `agent/actions/image_gen.py` (ComfyUI) e `agent/core/local_api.py`. Testes: `tests/test_inference_queue.py` (inclui o pai que solta a vaga antes de delegar). **Falta:** mostrar aguardando/executando na interface (o evento `inference_queue` sai de `AgentSession._inference_event`, mas `agent/gui.py` não o repassa); medir tempo total e trocas de modelo antes/depois; ajuste de concorrência local.

- **Entregar:** fila compartilhada pelos consumidores do mesmo recurso, estado aguardando/executando e cancelamento ainda na fila. Considerar chat, compactação, embeddings, voz, benchmark e ajudantes. Nuvem mantém paralelismo dentro dos limites existentes; o usuário poderá ajustar concorrência local depois de medição.
- **Arquivos:** `agent/core/agent_loop.py`, `agent/core/providers.py`, `agent/core/teamwork.py`, `agent/core/brain.py`, `agent/core/settings.py`; módulo proposto `agent/core/inference_queue.py`; `tests/test_teamwork.py`, `tests/test_agent_loop.py`, `tests/test_performance.py`.
- **Dependências:** LU-01/LU-04; deve existir antes de ComfyUI. **Aceite:** duas sessões disputando o mesmo recurso respeitam o limite; exceção/cancelamento sempre liberam a vaga; pai aguardando filho não causa deadlock; duas execuções sucessivas da mesma conversa têm identidades distintas; motores com nomes diferentes na mesma GPU não escapam da coordenação. Medir tempo total e trocas de modelo antes/depois, em vez de presumir que toda paralelização piora.
- **Inspiração:** [run-lanes.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/run-lanes.ts), [run-slot.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/run-slot.ts) e [vram-handoff.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/vram-handoff.ts). A referência serializa a faixa local; no Órbita a granularidade deve acompanhar recursos efetivamente compartilhados.

### LU-06 — Comparação de modelos com qualidade e custo · P1 · M · `[~]`

- **Estado:** parcial. `agent/core/model_eval.py:CASES`/`grade`/`measure`/`rank`/`run_comparison` (5 casos: PT-BR, JSON, instrução, documento, código; tokens do backend têm precedência; cancelado, prazo e erro saem do ranking) e `scripts/avaliar_modelos.py` (um `provedor:modelo` por rodada, sem trocar o modelo ativo). Testes: `tests/test_model_eval.py`. **Falta:** dois modelos na mesma rodada; aquecimento e tempo até a primeira resposta; quantização e contexto (hoje "não informada"); interface; caso de código executado em projeto temporário com `exec` (hoje só confere o texto); roteamento medido optativo.

- **Entregar:** comparar dois modelos com os mesmos casos, contexto e parâmetros; registrar aquecimento, primeira resposta, duração, tokens/s, custo quando conhecido, conclusão/cancelamento e acerto. Incluir PT-BR, JSON/ferramentas, instruções, documento com resposta conhecida e tarefa pequena de código.
- **Arquivos:** `agent/core/providers.py`, `agent/core/usage.py`, `agent/core/routing.py`, `agent/gui.py`, `agent/ui/web/app.js`; estender `scripts/medir_velocidade.py` ou criar `scripts/avaliar_modelos.py` se o propósito distinto justificar; `tests/test_performance.py` e testes de medição.
- **Dependências:** LU-02/LU-05. **Aceite:** tokens informados pelo backend têm precedência; chunks não viram tokens “reais”; saída cancelada, timeout ou incorreta não vence o ranking por velocidade; repetir casos com identificação do hardware/modelo/quantização/contexto. Testes de código rodam apenas em projeto temporário e com risco `exec`. Roteamento medido começa optativo, sem substituir catálogo automaticamente.
- **Inspiração:** [benchmark-run.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/benchmark-run.ts). Não reproduzir uma recomendação baseada só em testes curtos de resposta textual.

### LU-07 — Memória editável e isolada por projeto · P1 · G · `[x]`

- **Estado:** feito. `agent/memory/memory_manager.py:migrate_memory` (copia para `data/memory` com backup, sem apagar a origem) e `remember_fact`/`list_facts`/`update_fact`/`delete_fact`/`_visible` (id, origem, escopo global ou projeto, sem duplicata exata); `agent/actions/builtin_tools.py:remember` (projeto por padrão); painel em `agent/gui.py:listMemories`/`saveMemory`/`deleteMemory`; conversa grava `project` (`agent/core/brain.py`, `conversations.py:_extract_meta`) e `app.js:renderConvs` filtra pela pasta aberta. Testes: `tests/test_memory_scope.py`. **Ressalvas:** o `recall` ainda busca o log diário de todos os projetos (`get_relevant_context`); substituir decisões não existe; o filtro de conversas não tem teste automatizado.

- **Entregar em partes:** migrar memória/logs para `data/`; painel de listar/editar/apagar; registros com ID, origem e escopo; associação de conversas ao projeto; recuperação limitada por orçamento e projeto. Acrescentar deduplicação e substituição explícita de decisões depois da migração segura.
- **Arquivos:** `agent/memory/memory_manager.py`, `agent/core/config.py`, `agent/core/conversations.py`, `agent/core/agent_loop.py`, `agent/actions/builtin_tools.py`, `agent/gui.py`, `agent/ui/web/app.js`; novos testes de memória/migração e testes existentes de loop/projeto.
- **Dependências:** nenhum modelo de embeddings obrigatório; LU-04 para eventual processamento automático. **Aceite:** abrir projeto B não injeta fatos de A; fatos globais só quando assim classificados; migração idempotente com backup e sem perder logs; apagar remove também caches/índices; conteúdo externo não vira instrução nem memória confirmada sem política explícita. Conversas antigas continuam abrindo sem projeto definido.
- **Inspiração:** [memoryStore.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/stores/memoryStore.ts) e [testes de escopo](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/stores/__tests__/memory-scope.test.ts). Consolida Fases 2, 5, 7 e 9.

### LU-08 — Perguntar a documentos com fontes locais · P1 · G · `[x]`

- **Estado:** feito, primeira parte. `agent/core/documents.py:extract_document`/`chunk_segments`/`index_file`/`search` (TXT, Markdown e PDF com texto; arquivo, página e seção; limites de tamanho, páginas e fragmentos; índice por projeto com `EMBED_ID` e `DIM`; arquivo apagado sai; PDF sem texto pede OCR) e a ferramenta `agent/actions/builtin_tools.py:ask_documents`. Testes: `tests/test_documents.py` (corpus PT-BR de 20 perguntas, mínimo de 17 no top-5, ou seja 85%). **Ressalva:** o vetor é hash de palavras (`hash-v2`), busca lexical, não embedding semântico. DOCX, OCR e pastas monitoradas ficam para depois, como previsto.

- **Entregar em partes:** TXT/Markdown e PDF textual; extração em worker; fragmentos com arquivo/página/seção; embeddings locais e recuperação por projeto; anexar trechos relevantes e exibir fontes. DOCX depois; OCR e pastas monitoradas ficam para entrega posterior.
- **Arquivos:** novos módulos propostos `agent/core/documents.py` e `agent/core/retrieval.py` se extração e índice tiverem ciclos distintos; `agent/core/providers.py`, `agent/core/conversations.py`, `agent/core/agent_loop.py`, `agent/gui.py`, `agent/ui/web/app.js`; novos `tests/test_documents.py`/`tests/test_retrieval.py`.
- **Dependências:** LU-04/LU-05/LU-07. **Aceite:** corpus fixo PT-BR com ao menos 20 perguntas, trechos esperados entre os 5 primeiros em pelo menos 85% dos casos; citação aponta ao arquivo e página/seção recuperados; pergunta sem evidência não recebe fonte inventada; exclusão invalida índice; modelo/versão/dimensão do embedding integram a chave do índice; PDF sem texto informa necessidade de OCR. Limitar tamanho, páginas, fragmentos e tokens; não carregar scripts de documento nem recursos remotos. Meta de recuperação é proposta de aceite, ainda não medida.
- **Inspiração:** [rag.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/rag.ts). A extração da referência junta texto por página e fragmenta depois; preservar localização explícita no Órbita em vez de assumir que isso já vem pronto.

### LU-09 — Revisar alterações antes de gravar · P1 · G · `[~]`

- **Estado:** parcial. `agent/core/staged_writes.py:Store` (`propose_write`, edições acumuladas, leitura marcada "PROPOSTA, ainda não está no disco", `apply` com conflito por data/tamanho, `reject`, encoding e CRLF) e `staged_block` (terminal e MCP bloqueados); `agent/actions/builtin_tools.py` (ler, escrever, editar); `agent/gui.py:listProposals`/`applyProposal`/`rejectProposal`; imagem e clipe recusados nesse modo. Testes: `tests/test_staged.py`, `test_image_backend.py::test_staged_writes_do_not_touch_comfy_or_the_api`. **Falta:** aplicar não cria ponto de restauração (`checkpoints.py` não participa); `verify_project` roda sobre o disco, não sobre a proposta materializada; nada impede relatar como entregue uma proposta não aplicada.

- **Entregar:** modo opcional de mudanças propostas com diff por arquivo e aplicar/rejeitar; integrar aos checkpoints existentes. Leituras posteriores do agente enxergam a proposta, com identificação clara de que ela ainda não está no disco. Plan/Act continua funcionando.
- **Arquivos:** `agent/actions/builtin_tools.py`, `agent/core/checkpoints.py`, `agent/core/agent_loop.py`, `agent/gui.py`, `agent/ui/web/app.js`; `tests/test_checkpoints.py`, `tests/test_tools.py`, `tests/test_agent_loop.py`; módulo de propostas somente se necessário.
- **Dependências:** escopo de arquivos de LU-17 para fechar a entrega. **Aceite:** duas edições no mesmo arquivo se acumulam; criar e depois ler funciona; alteração externa entre propor/aplicar gera conflito em vez de sobrescrever; rejeitar não grava; encoding/CRLF preservados; proposta não aplicada não é relatada como entrega concluída. Executar testes contra propostas exige materialização isolada e permissão `exec`; shell/MCP não podem contornar o modo por outro caminho de escrita.
- **Inspiração:** [staged-writes.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/hooks/codex/staged-writes.ts). Difere do diff/restauração que o Órbita já mostra depois de alterar.

### LU-10 — Contexto de repositório e verificação estruturada · P1 · M · `[x]`

- **Estado:** feito. `agent/core/repo_map.py:RepoMap` (Python e JS/TS, ignora dados, modelos, venv, `.env` e links, cache invalidado por edição, orçamento fixo), usado por `agent/core/agent_loop.py`; DONE sem gate real vira PARTIAL. Testes: `tests/test_repo_map.py` (inclui `test_verify_requested_requires_actual_gate`), `test_agent_loop.py::test_summary_keeps_pending_heading_and_tool_pairs`. Ferramentas Git tipadas não foram feitas (eram condicionais).

- **Entregar em partes:** mapa compacto de arquivos/importações relevantes, começando por Python e JS/TS, com cache invalidado por mudança; preservar objetivo, decisões e pendências na compactação; associar a entrega ao resultado real de `verify_project`, não apenas ao texto “DONE”. Ferramentas Git tipadas só se eliminarem erros concretos do shell.
- **Arquivos:** `agent/core/mentions.py`, `agent/core/agent_loop.py`, `agent/core/integration.py`, `agent/actions/builtin_tools.py`; módulo `agent/core/repo_map.py` se necessário; `tests/test_mentions.py`, `tests/test_integration.py`, `tests/test_routing_compaction.py`, `tests/test_agent_loop.py`.
- **Dependências:** nenhuma para mapa/verificação; LU-06 para comparar qualidade. **Aceite:** ignora `.env`, dados, modelos, venv e links fora do projeto; cache reage à edição; mapa cabe em orçamento fixo e não substitui leitura do arquivo; falha de teste impede status verificado mesmo que o ajudante diga DONE. Compactação mantém pares tool-call/result e pendências em casos de regressão.
- **Inspiração:** [repo-map.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/agents/repo-map.ts), [repo_map.rs](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src-tauri/src/commands/repo_map.rs), [test-runner.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/agents/test-runner.ts) e [compact-summary.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/compact-summary.ts). A referência usa heurísticas de imports; o mapa não deve ser apresentado como análise semântica completa.

### LU-11 — Tarefas persistentes e segundo plano · P2 · G · `[~]`

- **Estado:** parcial. `agent/core/jobs.py:JobStore` (id, projeto, estado, saída limitada a 8.000 caracteres, parar, `interrupted` ao reabrir sem repetir) e `agent/gui.py:_run_job`/`startJob`/`listJobs`, que reutilizam `AgentSession` e o mesmo `approve` do chat. Testes: `tests/test_jobs.py`. **Falta:** custo (`_run_job` devolve sempre `cost_usd: None`); agenda e recorrência com fuso, pausa e histórico.

- **Entregar em partes:** jobs com ID, conversa/projeto, estado, saída limitada, custo e botão Parar; persistência e recuperação após reiniciar; só depois agenda/recorrência com fuso, pausa e histórico. Reutilizar execução do agente, sem um segundo loop paralelo com regras diferentes.
- **Arquivos:** `agent/core/agent_loop.py`, `agent/core/brain.py`, `agent/core/conversations.py`, `agent/core/usage.py`, `agent/gui.py`, `agent/ui/web/app.js`; novo `agent/core/jobs.py`; testes de jobs/cancelamento/orçamento.
- **Dependências:** LU-05, LU-07 e LU-17 para tarefas com escrita/execução. **Aceite:** aguardando não aparece como executando; parar cancela requisição/processo do job; reinício marca job interrompido e não repete efeitos externos; nenhum consentimento pendente fica invisível; orçamento compartilhado e MCP sequencial. Recorrência usa `America/Sao_Paulo` por padrão, evita sobreposição e explica execução perdida durante o app fechado. Não prometer funcionamento com o app fechado sem serviço próprio.
- **Inspiração:** [agent-tasks.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/agent-tasks.ts) e [bg-tasks.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/agents/bg-tasks.ts). Jobs em segundo plano não comprovam agenda durável; recorrência é extensão para o Órbita. Consolida Fases 4 e 9.

### LU-12 — Geração local com ComfyUI opcional · P2 · G · `[~]`

- **Estado:** parcial. `agent/actions/comfyui.py:ComfyClient` (só loopback, saúde, nós e modelos conferidos antes de enfileirar, workflow padrão texto→imagem, cancelamento só do próprio job, respostas limitadas) e `agent/actions/image_gen.py` (backend selecionável, fila `local-gpu`, sem cair em API paga); status em `agent/gui.py`. Testes: `tests/test_comfyui.py`, `tests/test_image_backend.py`. **Falta:** imagem→imagem e máscara; instalação gerenciada pela toolbox; rodada real registrando GPU, seed e duração.

- **Entregar em partes:** conectar ComfyUI existente e testar saúde/nós/modelos; um workflow pequeno de texto→imagem; imagem→imagem/máscara; só depois oferecer instalação gerenciada pela toolbox, com reparo explícito. Usar uma única ferramenta de geração com backend selecionável, mantendo metadados e APIs atuais.
- **Arquivos:** `agent/actions/image_gen.py`, `agent/core/toolbox.py`, `agent/core/toolbox_catalog.json`, `agent/core/settings.py`, `agent/gui.py`, `agent/ui/web/app.js`; adaptador proposto `agent/actions/comfyui.py`; `tests/test_toolbox.py` e novos testes do adaptador.
- **Dependências:** LU-02/LU-03/LU-04/LU-05; LU-17 para instalações. **Aceite:** falta de nó/modelo gera diagnóstico antes de enfileirar; progresso por job; cancelamento afeta somente o job do Órbita; serviço já aberto não é encerrado pelo app; baixar modelo/nó não ocorre silenciosamente. Rodada real registra GPU, workflow, seed, duração, arquivo e volta ao chat após liberação da VRAM. Sem GPU compatível, recurso fica opcional e o chat continua útil.
- **Inspiração:** [comfyui.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/comfyui.ts), [comfyui-ws.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/comfyui-ws.ts) e [vram-handoff.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/vram-handoff.ts).

### LU-13 — Galeria persistente e reutilização de artefatos · P2 · M · `[~]`

- **Estado:** parcial. `agent/core/gallery.py:Gallery` (`data/gallery.json` por projeto, com pedido, modelo, semente, backend e conversa; arquivo ausente continua na lista; tirar da lista é diferente de apagar o arquivo), gravada por `agent/actions/image_gen.py`; `app.js:loadGallery` com busca e Repetir. Testes: `tests/test_gallery.py`. **Falta:** resultados da caixa de ferramentas; filtros além da busca; abrir pasta; miniaturas em worker (hoje a tela carrega o arquivo original).

- **Entregar:** biblioteca por projeto/conversa com miniaturas, busca e filtros; abrir pasta, reutilizar imagem e repetir geração com prompt/seed/modelo/metadados disponíveis. Integrar resultados de APIs, toolbox e ComfyUI, sem uma galeria isolada por backend.
- **Arquivos:** `agent/actions/image_gen.py`, `agent/actions/builtin_tools.py`, `agent/core/conversations.py`, `agent/gui.py`, `agent/ui/web/app.js`, `agent/ui/web/app.css`; índice de artefatos proposto em módulo próprio apenas se necessário; testes de metadados e referências.
- **Dependências:** LU-07; LU-12 acrescenta geração local. **Aceite:** reabrir app preserva catálogo; arquivo ausente não derruba galeria; exclusão diferencia remover referência de apagar arquivo; não apagar entradas de outro projeto; repetir não promete resultado idêntico em backends não determinísticos. Miniaturas em worker e metadados tratados como dados externos.
- **Inspiração:** [createStore.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/stores/createStore.ts), [integração de resultados do chat à galeria](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/create/chat-gallery.ts) e o catálogo de [model-bundles.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/model-bundles.ts). O cartão de arquivos criados do Órbita já cobre a abertura imediata.

### LU-14 — Vídeo e ferramentas avançadas do estúdio · P3 · GG · `[~]`

- **Estado:** parcial, só um passo intermediário. `agent/actions/short_clip.py:render_clip` (ffmpeg junta até 12 imagens locais, no máximo 8 s e 1280×720; cancelar encerra só esse processo) e a ferramenta de clipe em `agent/actions/image_gen.py`. Testes: `tests/test_short_clip.py`. Não é modelo de vídeo. **Falta:** imagem→vídeo e texto→vídeo por modelo, LoRA, máscara, personagem e os experimentos.

- **Entregar por extensões independentes:** imagem→vídeo curto; depois texto→vídeo; LoRA com seleção/intensidade; edição com máscara e consistência de personagem. Remoção de fundo/upscale local, música, personagem falante e treinamento de LoRA ficam como experimentos separados, condicionados a demanda/hardware/licença. Cada fluxo terá um modelo/workflow validado antes de ampliar catálogo.
- **Arquivos:** `agent/actions/comfyui.py` se criado em LU-12, `agent/core/toolbox_catalog.json`, `agent/gui.py`, `agent/ui/web/app.js`; metadados do pipeline atual e testes do adaptador. Skills criativas só mudam em tarefa específica com necessidade demonstrada.
- **Dependências:** LU-12/LU-13; FFmpeg no PATH ou instalado pela toolbox para fluxos que o exigirem. **Aceite:** duração/resolução/frames limitados antes da execução, cancelar remove apenas a própria tarefa, resultado reproduzível por parâmetros registrados; medir VRAM, tempo e falhas por workflow. Falta de memória não leva a repetir indefinidamente nem a trocar para nuvem. Treinamento não entra no instalador básico.
- **Fonte:** [bundles de mídia](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/api/model-bundles.ts) e [descrição das modalidades](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/README.md). A própria referência declara upscale e apagar objeto como fluxos cloud; não marcá-los como capacidades locais já comprovadas.

### LU-15 — Portabilidade de conversas e perfis · P2 · M · `[x]`

- **Estado:** feito, primeira parte. `agent/core/exchange.py:export_conversation`/`conversation_markdown`/`import_conversation`/`export_profile`/`import_profile` (formato versionado, segredos retirados, importar duas vezes não duplica, versão desconhecida recusada); `agent/gui.py:exportCurrentConversation`/`exportCurrentProfile`/`importPackage`. Testes: `tests/test_exchange.py`. Importadores de outros produtos ficam para depois, como previsto.

- **Entregar em partes:** exportação e importação do formato próprio versionado, Markdown legível e exportação de perfis; depois importadores de exportações de outros produtos, um por vez e a partir de fixtures públicas/sintéticas. Incluir origem e modelo efetivo por resposta quando disponíveis.
- **Arquivos:** `agent/core/conversations.py`, `agent/core/profiles.py`, `agent/gui.py`, `agent/ui/web/app.js`; novos testes de formatos/migrações. Adaptadores externos só ganham módulo quando implementados.
- **Dependências:** LU-07 para associação ao projeto; formato próprio pode começar antes. **Aceite:** exportar→importar preserva mensagens, ordem e metadados compatíveis; importar duas vezes não duplica; campos desconhecidos não executam ferramentas nem ativam prompts/permissões automaticamente; caminhos de anexos passam por validação; exportação de perfis não inclui chaves, tokens ou dados de conta.
- **Inspiração:** [chat-export.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/chat-export.ts) e [chatStore.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/stores/chatStore.ts). Não prometer compatibilidade com formatos de terceiros sem amostras e testes da versão do formato.

### LU-16 — Voz interrompível em português · P2 · G · `[x]`

- **Estado:** feito. `agent/voice/speaker.py:stop`/`quiet_for_listen`/`_chunks`/`note_user_speech_ended`/`_mark_first_audio`; `agent/gui.py` envia `voice_state` (ouvindo, pensando, falando); `app.js` anota o tempo até o primeiro áudio. Testes: `tests/test_speaker_interrupt.py`. **Ressalvas:** a fala é cortada ao abrir o microfone ou em Parar, não por detecção de voz durante a reprodução, e o corte vale a partir do pedaço seguinte; a latência não registra GPU/CPU e não há medição real.

- **Entregar:** interromper a reprodução quando o usuário começa a falar, cancelamento propagado para geração, estados claros de ouvindo/pensando/falando e métricas de latência. Preservar ditado e seleção de voz atuais; começar pelo stack existente antes de adotar Pipecat ou outro serviço.
- **Arquivos:** `agent/voice/listener.py`, `agent/voice/speaker.py`, `agent/voice/dictation.py`, `agent/core/brain.py`, `agent/gui.py`, `agent/ui/web/app.js`; `tests/test_dictation.py` e novos testes de turnos de áudio.
- **Dependências:** LU-04/LU-05. **Aceite:** roteiro PT-BR com acentos e interrupções, sem interpretar a própria voz sintetizada como novo comando; modelo de texto local respeita o destino escolhido; cancelar não deixa áudio ou requisição órfãos; medir fim da fala→primeiro áudio com GPU/CPU identificados. Aprovação de ferramentas mantém as mesmas permissões do chat.
- **Inspiração:** [VOICE.md](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/VOICE.md) e [voice_loop](https://github.com/PurpleDoubleD/locally-uncensored/tree/961621610ba365160c99696edbc574c9bd5474f1/src-tauri/resources/voice_loop). A referência declara voz beta em inglês; isso não comprova qualidade em português.

### LU-17 — Escopo de arquivos e controle do PC com interrupção · P1 · G · `[~]`

- **Estado:** parcial. `agent/core/tools.py:ToolContext.reject_write` (`file_scope = "project"`: escrita fora da pasta recusada, inclusive por link) e `agent/core/pc_pause.py:PcPause` com `agent/actions/system_control.py` (mouse fora do lugar pausa; só volta com `agent/gui.py:resumePc`). Testes: `test_tools.py::test_project_scope_blocks_writes_outside_and_through_links`, `tests/test_pc_pause.py`. **Falta:** leitura por pasta e permissões por categoria/ferramenta; escopo por aplicação para mouse, teclado e screenshot; parada global; terminal e MCP não ficam presos à pasta (a tela avisa).

- **Entregar em partes:** permissões por pasta/projeto e categoria/ferramenta; depois escopo por aplicação para mouse/teclado/screenshot, pausa por intervenção humana e parada global. Manter `read`/`write`/`exec` e modos atuais como base, com migração explícita das novas restrições.
- **Arquivos:** `agent/core/tools.py`, `agent/core/agent_loop.py`, `agent/actions/builtin_tools.py`, `agent/actions/system_control.py`, `agent/gui.py`, `agent/ui/web/app.js`; `tests/test_tools.py`, `tests/test_agent_loop.py`, `tests/test_grok_bridge.py` e testes de controle do PC.
- **Dependências:** nenhuma para iniciar; fecha antes de jobs autônomos e acesso remoto. **Aceite:** travessia, symlink/junction e caminho absoluto não contornam escopo; subagentes e ponte Grok recebem as mesmas restrições; modo plano não grava/executa; MCP não é declarado restrito por pasta sem enforcement no servidor/isolamento — se não houver, bloquear ou explicar incompatibilidade naquele modo. Testes continuam `exec`. Controle do PC não é retomado automaticamente após o usuário assumir a interação; aprovações sensíveis não são inferidas de texto externo.
- **Inspiração:** [permissionStore.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/stores/permissionStore.ts), [COMPUTER-CONTROL.md](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/COMPUTER-CONTROL.md) e [pause.ts](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src/lib/computer/pause.ts). Não portar a política inteira da referência sem definir o comportamento esperado para o Órbita.

### LU-18 — Distribuição, CI e atualização autenticada · P1 · G · `[~]`

- **Estado:** parcial. `.github/workflows/tests.yml` (pyflakes e pytest em Windows e Ubuntu, Python 3.10 e 3.12); `scripts/build_package.py` e `packaging/orbita_entry.py` (protótipo PyInstaller com lista de recursos permitidos, sem dados nem pesos); `agent/core/update_auth.py:verify_manifest` (HMAC-SHA256 com chave do ambiente) e `agent/core/updater.py:apply_verified` (recusa antes de gravar, devolve os arquivos se a gravação quebra). Testes: `tests/test_update_auth.py`, `tests/test_packaging.py`. **Falta:** instalador Windows e pacote Linux testados; assinatura de chave pública; ligar `apply_verified` ao botão de atualizar (ainda usa o ZIP público); conferir o resultado do Actions.

- **Entregar em partes:** CI com gates já exigidos; instalador Windows e pacote Linux sobre o stack atual; manifesto de componentes/opcionais; assinatura/verificação do canal de atualizações, preservando backups. A revisão de licença acompanha cada componente efetivamente distribuído.
- **Arquivos:** `.github/workflows/tests.yml` (novo), `requirements.txt` e scripts de empacotamento a definir pelo protótipo; `agent/core/updater.py`, `agent/core/toolbox.py`; `tests/test_updater.py`, `tests/test_toolbox.py`, `tests/test_portability.py`. Tauri permanece avaliação separada, sem migração nesta entrega.
- **Dependências:** CI pode começar imediatamente; instalador depende da escolha validada em LU-03/LU-12. **Aceite:** instalação limpa abre sem terminal e oferece opcionais sem baixá-los sozinha; payload/manifesto com assinatura inválida é recusado antes de executar; interrupção permite recuperar versão anterior; atualização nunca toca conversas/chaves/modelos. Validar Windows e Linux em ambientes reais/isolados identificados; não declarar macOS suportado por herança da referência.
- **Inspiração:** [SECURITY.md](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/SECURITY.md) e [tauri.conf.json](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src-tauri/tauri.conf.json). Canal assinado e assinatura do instalador são coisas diferentes; a documentação da referência distingue os dois.

### LU-19 — API local opcional para outros clientes · P3 · G · `[x]`

- **Estado:** feito. `agent/core/local_api.py:LocalApi`/`maybe_start`/`default_chat`/`_Handler` (desligada por padrão, só 127.0.0.1, token do ambiente, `/v1/models` e `/v1/chat/completions` com streaming, id `provedor:modelo`, origem conferida, corpo até 256 KB, sem ferramentas, cancelamento libera a vaga). Testes: `tests/test_local_api.py`.

- **Entregar:** avaliar demanda frente a usar Ollama/LM Studio diretamente; se necessário, expor inferência por `/v1/models` e `/v1/chat/completions`, com IDs qualificados por provedor e streaming. Sem execução de ferramentas do PC no MVP; a ponte Grok existente continua com seu contrato específico.
- **Arquivos:** novo `agent/core/local_api.py` se aprovado pelo experimento; `agent/core/providers.py`, `agent/core/settings.py`, `agent/core/brain.py`; testes HTTP locais e testes de streaming/cancelamento.
- **Dependências:** LU-04/LU-05/LU-17. **Aceite:** desligada por padrão, escuta só em loopback, autenticação obrigatória com segredo no `.env`; nomes coincidentes entre motores não colidem; ID de resposta bate com ID listado; cancelamento do cliente encerra geração e libera vaga; sem expor chaves dos provedores. Testar limites de payload e origins permitidas. Publicação fora da máquina fica fora desta tarefa.
- **Inspiração:** [local_api.rs](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src-tauri/src/commands/local_api.rs).

### LU-20 — Cliente remoto/celular, começando pela LAN · P3 · GG · `[~]`

- **Estado:** parcial, só o servidor. `agent/core/remote_access.py:Pairing`/`RemoteServer`/`open_remote`/`allowed_host` (desligado por padrão, só endereço privado ou loopback, código de 5 minutos, 5 erros queimam o código, revogação imediata, aparelho preso ao projeto, sem ferramentas). Testes: `tests/test_remote_access.py`. **Falta:** o cliente (interface de chat mínima ou aplicativo); transporte protegido (hoje HTTP simples na LAN). Internet fica para depois.

- **Entregar por experimento:** interface de chat mínima na rede local com pareamento e dispositivos revogáveis; internet/túnel somente em tarefa posterior, após avaliar demanda e fronteiras de dados. O servidor do frontend desktop não deve simplesmente ser publicado na rede.
- **Arquivos:** novo `agent/core/remote_access.py` e cliente remoto a definir no protótipo; `agent/core/conversations.py`, `agent/core/settings.py`, `agent/core/brain.py`; testes de autenticação, revogação e separação de sessões.
- **Dependências:** LU-11/LU-17/LU-19 e distribuição estabilizada. **Aceite:** desativado inicialmente; pareamento expira, tentativas limitadas e revogação imediata; sessões não leem projetos alheios; nenhum cliente remoto aprova execução/controle do PC no MVP. Definir transporte protegido e armazenamento de credenciais antes do piloto; conexão fora da LAN informa intermediários e sua capacidade de acesso aos dados. Não vender túnel como criptografia ponta a ponta.
- **Inspiração:** [remote.rs](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/src-tauri/src/commands/remote.rs) e [limites declarados no README](https://github.com/PurpleDoubleD/locally-uncensored/blob/961621610ba365160c99696edbc574c9bd5474f1/README.md).

## 8. Próximo pacote recomendado

O primeiro pacote (LU-01, LU-02, LU-03(a) e LU-04, com o CI de LU-18) já tem código. Antes de ampliar, fechar o que ele deixou aberto:

1. **Validação real da onda 1:** abrir a janela, achar Ollama/LM Studio de verdade, baixar e cancelar um modelo do catálogo, conversar em modo somente local e conferir o primeiro resultado do Actions.
2. **Pequenos acertos de interface:** estado aguardando/executando da fila (LU-05) e destino dos dados por operação (LU-04).
3. **LU-02 com medição:** rodar `scripts/avaliar_modelos.py` nos três modelos do catálogo em PT-BR e registrar o resultado no catálogo, o que pede antes os itens de LU-06 (dois modelos por rodada, aquecimento, quantização e contexto).
4. **LU-09 com checkpoints:** aplicar a proposta pelo ponto de restauração, para que Desfazer funcione.

Sequência por tarefa: (1) teste/contrato e baseline; (2) implementação mínima no núcleo existente; (3) integração em worker e interface; (4) testes focados e rodada real do fluxo; (5) gates, Diário e commit. Downloads GGUF diretos, servidor embutido e instalação gerenciada do ComfyUI continuam depois desse caminho básico.

## 9. Como comparar os dois programas em testes futuros

Usar instalação separada da referência e a mesma máquina/modelo/quantização/contexto. Não apontar os dois apps simultaneamente para pastas de gravação compartilhadas. O ensaio deve produzir tabela com versão, hardware, carga fria/quente, parâmetros, duração, resultado e logs sem segredos.

| Cenário | O que medir e observar |
|---|---|
| Primeira execução | Passos e tempo até primeira resposta; motor existente reaproveitado; caminho claro sem GPU |
| Download interrompido | Estado ao cancelar, reiniciar e tentar de novo; integridade; consumo de disco |
| Chat PT-BR | Tempo até primeiro token e resposta final, acentos, instruções e custo conhecido |
| Ferramentas | Schema/argumentos, sucesso verificável, permissão recusada e recuperação sem loop |
| Dois consumidores locais | Tempo total, trocas de modelo, cancelamento e responsividade |
| Documento | Precisão dos trechos recuperados, localização da fonte e pergunta sem resposta |
| Código | Mesmo projeto pequeno: proposta, diff, execução autorizada dos testes e restauração |
| Criação | Mesmo workflow/seed; VRAM, tempo, cancelamento e retorno ao chat |
| Voz | Entendimento em PT-BR, latência e interrupção sem realimentação do áudio |
| Reinício/atualização | Conversas, projetos, modelos, permissões e jobs preservados ou recuperáveis |

Até 19/10 esse ensaio não foi feito. Instalar grandes modelos, gerar mídia ou usar APIs pagas não fez parte do planejamento nem da auditoria.

## 10. Invariantes e definição de pronto das implementações

- Preservar o formato interno de mensagens e blocos nativos de provedores, tool-calling por prompt, orçamento compartilhado e compatibilidade de conversas existentes.
- Não executar trabalho pesado na UI. MCP continua sequencial. Coordenar inferência não significa paralelizar MCP.
- HTML externo/modelo/MCP/arquivo só passa por `render.markdown_html`/`esc()` ou inserção textual segura; sem CDN/JS externo. Arquivos e documentos são dados, nunca instruções.
- Segredos somente no `.env`; preferências e índices em `data/`; modelos em `models/` ou motores externos, sempre fora do Git. Backups de configuração antes de teste que a altere.
- Preservar riscos: leitura `read`, alteração `write`, execução/testes/controle `exec`; nenhum recurso novo reduz risco para evitar confirmação.
- Bug exige teste que falha antes; feature exige teste do comportamento, bordas e cancelamento. UI exige conferência visual real ou `QWidget.grab()`, além de testes de contrato.
- Gates por entrega: `venv\Scripts\python.exe -m pyflakes agent tests launcher.py setup_voz.py` sem avisos e `venv\Scripts\python.exe -m pytest tests -q` sem falhas; registrar números reais e testes pulados.
- Medidas reais de hardware/desempenho são separadas de estimativas. Recurso sem validação real permanece parcial; não marcar todas as ondas como concluídas por concluir o plano.

## 11. Escolhas que ficam para evidência de uso

Não adotar o catálogo inteiro de modelos, contas/assinaturas cloud da referência ou dependências de estúdio no núcleo do app. O valor do projeto para esta evolução está nos fluxos de uso e nos contratos técnicos; “uncensored” não é evidência de qualidade de ferramentas, PT-BR ou adequação ao hardware.

Motor embutido, treinamento de LoRA, música/personagem falante, API geral e acesso pela internet têm custo de manutenção distinto. Permanecem registrados, mas só avançam depois dos fundamentos e de uma hipótese de uso testável. Manter a identidade de agente pessoal do Órbita e adicionar capacidades opcionais, em vez de transformar toda instalação num estúdio pesado.

## 12. Verificação

Auditoria de 19/10/2026: cada estado da seção 7 foi conferido no código (símbolos citados) e não só no ROADMAP. Os testes citados como evidência rodaram nesta árvore: os 22 arquivos de teste dos cartões (`test_local_engines`, `test_local_catalog`, `test_model_manager`, `test_local_policy`, `test_inference_queue`, `test_model_eval`, `test_memory_scope`, `test_documents`, `test_staged`, `test_repo_map`, `test_jobs`, `test_comfyui`, `test_image_backend`, `test_gallery`, `test_short_clip`, `test_exchange`, `test_speaker_interrupt`, `test_pc_pause`, `test_update_auth`, `test_packaging`, `test_local_api`, `test_remote_access`) deram **168 aprovados em 13,55 s**, e os três testes isolados de `test_tools.py`/`test_agent_loop.py` deram **3 aprovados**. Nenhuma janela foi aberta e nenhum motor real foi usado.

Entrega de planejamento (18/10/2026):

- `venv\Scripts\python.exe -m pyflakes agent tests launcher.py setup_voz.py`: código de saída 0, nenhum aviso.
- `venv\Scripts\python.exe -m pytest tests -q`: **192 passed, 2 skipped in 64.75s**. São resultados da suíte existente; não validam funcionalidades futuras nem a referência.
- Backup de `data/settings.json` criado fora do repositório antes dos gates; hash conferido ao final, arquivo preservado. Nenhum arquivo da interface ou configuração foi editado por esta entrega; conferência visual não se aplica ao diff documental.
- Verificação de integridade do plano: 20 IDs únicos LU-01 a LU-20 correspondentes no documento e no ROADMAP, 38 fontes do GitHub encontradas na cópia do commit fixado, links locais/UTF-8 e `git diff --check` conferidos antes do commit.
