# Integração funcional da Cassandra

Referência inspecionada: `C:\Users\Administrator\Downloads\cassandra-agent-main`, em 21/10/2026.
Implementação própria sobre os contratos do Órbita; a referência não é dependência de execução.

## Objetivo e limites

Disponibilizar os comportamentos executáveis da Cassandra além das skills já importadas:
conta DeepSeek Web, conversa temporária, anexos de arquivos/pastas, chat no navegador,
consulta periódica de pedidos, atalhos de terminal e busca Brave/Google.
Preservar provedores existentes, permissões por risco, política somente local,
cancelamento, orçamento de contexto e carregamento progressivo de skills.
Não copiar persona nem interpretar slogans de prompt como funcionalidades de software.

## Plano e arquivos

1. Testes de comportamento para memória temporária e anexos; implementação em
   `brain.py`, `memory_manager.py`, `mentions.py`, `gui.py` e `ui/web/`.
2. Adaptadores independentes `deepseek_web.py`, `browser_chat.py`/`ui/browser.html`,
   `prompt_polling.py` e fontes de busca em `actions/web_search.py`, com testes próprios.
3. Integrar provedor em `providers.py`/`settings.py`, opções em `main.py` e atalhos
   no terminal; documentar uso sem mudar versão ou configurações pessoais.
4. Revisar os contratos; executar lint, suíte completa e conferir a interface real.

Também entram o recurso HTML no empacotamento e testes da página Qt real.

## Critérios de aceite

- Conversa temporária não grava conversa nem memória diária/fatos; sair do modo
  restaura a memória persistente. Não apaga conversas anteriores. Checkpoints do
  turno temporário são desativados. Arquivos criados por ferramentas, logs técnicos,
  contadores de tokens e retenção do provedor não fazem parte dessa promessa.
- Seletor de arquivos/pastas e CLI anexam texto com cotas, avisos de omissão,
  exclusão de segredos e sem seguir links para fora da pasta. Imagens continuam
  usando o caminho de visão dos provedores.
- DeepSeek Web oferece login manual, sessão dedicada/CDP, texto e raciocínio,
  cancelamento e diagnóstico; testes de contrato não equivalem a login real.
- Chat no navegador usa o mesmo loop agêntico, autenticação local, serialização
  dos turnos, Parar e autorização explícita para ferramentas de risco.
- Polling usa URL explícita, intervalo finito, cancelamento e deduplicação dos
  pedidos concluídos; não altera permissões nem permite tráfego no modo somente local.
- Busca usa fontes alternativas quando a anterior falha ou fica vazia; sem chaves
  não faz chamadas às APIs pagas, e nunca imprime chaves.
- Gates: pyflakes sem avisos, pytest completo sem falhas e interface conferida.

## Equivalências preservadas

| Cassandra | Órbita |
|---|---|
| Shell em loop e `--allow-shell` | `run_shell` com risco `exec`, permissões e loop agêntico |
| Streaming e DeepThink | eventos de texto e raciocínio dos provedores |
| Skillogy | `when`, `use_skill`, perfis e catálogo Cassandra existente |
| Histórico e compactação | conversas salvas, memória e resumo com orçamento |
| Busca e leitura das fontes | `web_search`, `fetch_url`, `web_research` |
| Persona, PG e STATE_DUMP | texto configurável de perfil; sem motor adicional na referência |
| Retry por frases de recusa | nova tentativa explícita pelo usuário; sem injetar overrides |

O detector de recusa da referência testa a mensagem errada antes de inserir a
resposta. Não se replica esse defeito nem se executa bloco Markdown como comando.

## Validação e uso

### Janela do Órbita

- O clipe seleciona arquivos/imagens. O botão de pasta inclui textos das subpastas.
- O relógio ao lado de Nova conversa alterna o modo temporário. Trocar o modo começa
  uma conversa vazia. Abrir uma conversa salva sai do modo temporário e atualiza o selo.
- Configurações → Conta DeepSeek → Entrar na conta abre uma janela visível. Faça
  login e qualquer verificação apresentada pelo site. Depois selecione DeepSeek Web.
  Os modelos `default`/`expert` correspondem a Instant/Expert; `-thinking` ativa raciocínio.

### Terminal e navegador

Na pasta do Órbita, em PowerShell:

```powershell
# powershell · uso · Órbita · Windows · Python do ambiente virtual
.\venv\Scripts\python.exe -m agent.main --web
.\venv\Scripts\python.exe -m agent.main --text --temporary
.\venv\Scripts\python.exe -m agent.main --prompt "Analise os arquivos" --attach "C:\caminho\projeto"
.\venv\Scripts\python.exe -m agent.main --deepseek-login
.\venv\Scripts\python.exe -m agent.main --text --model deepseek_web:expert-thinking
.\venv\Scripts\python.exe -m agent.main --poll --poll-url "https://sua-fila/agent/pending-prompts" --delay 30
```

`--web` abre um endereço local com token temporário no fragmento; use o endereço
completo mostrado. `--port` escolhe a porta. A página oferece seleção de modelo/perfil,
conversa temporária, anexos textuais e confirmação de ações. Parar cancela também
aprovações pendentes. O servidor atende somente neste computador. Fechar a aba tenta
cancelar o turno e descartar a conversa temporária; a entrega desse aviso depende do navegador.

`--temporary` tem o alias `--ghost`. A memória desse modo não é gravada, inclusive
fatos registrados por `remember`. `--allow-shell` ativa as permissões **Livre** nesta
execução; salvar outra preferência não torna essa opção permanente. Execução segue
via ferramenta `run_shell`, com risco `exec`, e não por blocos Markdown arbitrários.

No modo texto: `:web termo`/`:w termo`, `:log`/`:historico`/`!log`, `:clear`,
`:temporary on`/`off`, `:attach caminho` e `:skill nome`. `@arquivo` continua disponível.
Ctrl+C interrompe uma resposta e permite o próximo pedido; no campo de entrada, encerra.
Rich mostra Markdown ao vivo; sem ele, continua em texto simples.

### Configuração externa e limites

- Busca: DuckDuckGo primeiro, Brave quando a primeira fonte falha/fica vazia, Google
  quando necessário. Chaves no `.env`: `BRAVE_SEARCH_API_KEY`, `GOOGLE_SEARCH_API_KEY`,
  `GOOGLE_SEARCH_CX`. Sem as chaves, não chama essas APIs. Parâmetros conferidos nas
  documentações de [Brave](https://api-dashboard.search.brave.com/app/documentation/web-search/codes)
  e [Google](https://developers.google.com/custom-search/v1/using_rest).
- Fila: `GET` autenticado retorna `[{"id": "pedido-1", "prompt": "..."}]`, ou um
  objeto com `body` contendo essa lista em JSON. `CASSANDRA_API_KEY` fornece o bearer;
  `CASSANDRA_API_URL` pode fornecer a base (o programa acrescenta `/agent/pending-prompts`).
  `--poll-once` consulta uma vez. Sem ACK remoto, a deduplicação vale só até encerrar
  o programa; a fila deve retirar pedidos concluídos para não repeti-los após reiniciar.
  Cada pedido abre uma conversa. Erros de modelo/cancelamento não são marcados como sucesso.
- DeepSeek: perfil em `data/deepseek_web/profile`, ou `ORBITA_DEEPSEEK_PROFILE_DIR`.
  `DEEPSEEK_CDP_URL` aceita um Chrome local já aberto para login por CDP. A sessão é
  gerida pelo navegador, sem copiar cookies ou tokens da Cassandra. Se faltar Chromium:
  `venv\Scripts\python.exe -m playwright install chromium`.
- `ORBITA_DEEPSEEK_WEB_SEARCH=1` ativa a busca do site. `ORBITA_DEEPSEEK_DELETE_CHAT=1`
  pede exclusão remota só da sessão criada pela chamada atual; desativado por padrão.
  Falha de exclusão é mostrada e não é tratada como sucesso. Isso não garante ausência
  de retenção no serviço. O conector usa o site e pode precisar de adaptação quando ele mudar.
- DeepSeek Web não envia imagens; use um provedor com visão. Anexos textuais funcionam.
  Nenhum login de conta real foi iniciado ou validado durante a implementação.
- Anexos desktop/CLI: 200 entradas, 12 mil caracteres por arquivo e 30 mil no total;
  arquivos grandes/binários ficam indicados como omitidos. A seleção de pasta inclui textos,
  sem seguir links. Anexos no navegador: 40 arquivos, 100 KB por arquivo e 500 KB no total.
- Modo somente local bloqueia DeepSeek Web, login de nuvem, pesquisa e consulta à fila.

Testes de navegador usam servidores locais e não comprovam que uma conta DeepSeek
real está autenticada. Os resultados finais dos gates ficam registrados no Diário.

### Resultado desta integração (21/10/2026)

Pyflakes sem avisos; JavaScript validado; suíte completa: **575 aprovados, 2 pulados,
123,07 s**. Página real Qt e Chromium conferidos. Uma reprodução isolada com o Brain
real completou ferramenta de escrita após autorização e não persistiu histórico
temporário. Nenhuma conta DeepSeek real nem API paga foi usada nos testes. A versão
continua `0.4.1-alpha`; estas mudanças estão em Não lançado.
