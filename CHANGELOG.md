# Changelog

Todas as mudanças relevantes do Órbita ficam registradas aqui.
Formato inspirado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), versões no estilo
[SemVer](https://semver.org/lang/pt-BR/) em fase alfa.

## Como versionamos

- **Correções e melhorias pequenas não mudam a versão.** Elas entram no GitHub normalmente e são anotadas em
  **[Não lançado]** abaixo.
- **Atualização grande** (um conjunto de recursos novos, ou algo que muda o jeito de usar) sobe o segundo número:
  `0.1.0-alpha` → `0.2.0-alpha`. As notas de "Não lançado" passam para a versão nova e o git ganha a tag
  `v0.2.0-alpha`.
- **Correção urgente** entre duas versões grandes sobe o terceiro número: `0.1.1-alpha`.
- **`1.0.0`** só quando o programa for declarado estável. Até lá, o sufixo `-alpha` avisa que ainda pode mudar.
- Nenhuma versão vem compilada: o Órbita é distribuído só como código-fonte.
- A versão fica em `agent/__init__.py` e aparece em Configurações › Sobre.

## [Não lançado]

### Melhorias
- **Ferramentas de criação** (página Conexões): ImageMagick, OpenSCAD, Blender, Godot e FFmpeg, que a IA sabe usar
  para editar imagem, modelar 3D, fazer jogos e vídeo. Nada vem instalado; baixa só com clique ou com permissão do
  agente, de URL oficial fixa e com conferência de SHA-256. Novas skills: `editar-imagem`, `modelagem-3d`,
  `jogos-godot`, `jogos-web` e `video-ffmpeg`.
- **Ditado por voz**: clique no microfone (ou Ctrl+M), fale e o texto vai aparecendo no campo enquanto você fala;
  clique de novo (ou Enter) para terminar e revise antes de enviar. Esc cancela. Funciona com o agente trabalhando.
  Com chave da Groq (plano grátis) ou da OpenAI, transcreve na nuvem, como o ChatGPT e o Claude: rápido em qualquer PC,
  mesmo fraco. Sem chave, roda neste PC com um modelo leve (~150 MB). Placa NVIDIA e modelos maiores são opcionais em
  Configurações › Voz. A conversa por voz antiga (fala e ouve a resposta) fica em Ctrl+K.
- **Equipe mais fluida**: por padrão os ajudantes são cópias do agente principal — mesma API e mesmo modelo, cada um
  com uma tarefa — trabalhando ao mesmo tempo na mesma pasta. O agente não troca mais sozinho para um modelo local.
  Na página Equipe dá para escolher "Automático por especialidade", se preferir.
- **Liberdade por modelo**: modelos de ponta (Claude, GPT-5, Fable, Grok 4, Gemini Pro, DeepSeek) trabalham com mais
  autonomia e o dobro de passos; modelos locais pequenos trabalham em "modo foco", um passo por vez.
- **Equipe que se encaixa**: antes de dividir partes que precisam combinar (HTML/CSS/JS, front/back), o agente
  principal define um contrato (nomes de classes, IDs, arquivos, funções) que vai igual para todos os ajudantes. Quando
  eles terminam, o Órbita confere sozinho se HTML, CSS e JS batem e devolve ao agente o que não encaixa, para ele
  corrigir antes de dizer que está pronto.
- **O ambiente sugere a equipe**: em pedidos grandes (site/sistema do zero, várias partes listadas, "3 agentes"...),
  o agente recebe naquele turno uma sugestão de quantos ajudantes usar e um fluxo em 3 fases (contrato → partes em
  paralelo → integração). Pedidos pequenos não recebem nada. Cada ajudante sabe o que os outros estão fazendo.
  Até 6 ao mesmo tempo com modelos de ponta na nuvem, 4 nos demais e 2 com modelo local; o resto espera na fila
  (ajustável na página Equipe).
- **Agentes testam sites sem mexer na sua tela**: nova ferramenta `check_web_page` abre a página num navegador
  invisível e mostra erros de JavaScript, arquivos que não carregaram, links quebrados, conteúdo vazando no celular e,
  se pedido, uma captura pequena; também roda um script de teste (ex.: clicar em "adicionar ao carrinho").
- Ajudantes da equipe não controlam mais mouse, teclado e tela do usuário, e cada um para sozinho ao passar de 300 mil
  tokens (entrega o que tem como PARTIAL), em vez de gastar o saldo testando sem fim.

### Corrigido
- O terminal do agente não trava mais quando um comando abre um servidor (ex.: `python -m http.server`): servidores
  e comandos que não terminam vão para segundo plano (com PID, porta e log), e no fim do prazo o Órbita encerra o
  comando com tudo o que ele abriu.
- A barra de digitar não some mais durante trabalhos longos: o painel Ao vivo crescia e empurrava a página para fora
  da janela; agora ele rola por dentro. Respostas com linhas longas também não cortam mais o texto à direita.
- Raciocínio do modelo em bloco expansível: aberto enquanto ele pensa (texto completo, com tempo), fecha sozinho
  quando ele começa a escrever e pode ser reaberto e copiado. Raciocínio de subagentes não mistura no chat.
- Botão Compactar (topo do chat ou Ctrl+K): resume o histórico na hora, em segundo plano, num resumo estruturado
  (objetivo, feito, decisões, estado atual, próximos passos), mantendo o último pedido inteiro. A compactação
  automática perto do limite continua valendo.
- Ao vivo mais legível: tipo de evento destacado, horário e itens longos limitados a 3 linhas.

## [0.2.0-alpha] — 2026-10-16

### Melhorias
- **Conversas pelo botão direito**: na lista de conversas, o botão direito abre um menu com Renomear (edição na
  própria linha: Enter salva, Esc cancela) e Apagar (com confirmação; se for a conversa aberta, começa uma nova).
  A paleta de comandos (Ctrl+K) ganhou "Renomear conversa" e "Prompt da conversa".
- **Prompt da conversa**: um botão no topo do chat define instruções fixas só daquela conversa, aplicadas em todos os
  turnos (desde o primeiro, mesmo em conversa nova), além do prompt do perfil. Fica salvo com a conversa e volta ao
  reabri-la; um selo discreto mostra quando está ativo.
- **Busca de modelos**: Configurações › Modelos e o editor de perfil têm um campo de busca que ignora maiúsculas e
  acentos e aceita partes do nome ("claude son" acha "anthropic/claude-sonnet-…"), com contagem ("1 de 380"), modelo
  em uso destacado, setas + Enter para escolher e busca automática da lista quando ela está vazia. O editor de perfil
  não usa mais `<datalist>`.
- Ícones próprios para os agentes, no lugar dos emojis do Windows: cada perfil tem símbolo e cor exclusivos
  (estrela em órbita, código, revisão, pesquisa, criação, DNA, raio, automação, liderança, robô). O editor de
  perfil ganhou um seletor de ícone; perfis antigos com emoji passam a usar o ícone correspondente sozinhos.
- Agentes de pesquisa recomendam modelo ou servidor MCP pela skill `descobrir-agente`, carregada só quando o
  pedido é esse. A tabela de modelos com acesso entra nesse momento, não em todo turno. A skill não configura nada.
- O prompt deixa de despejar o corpo das skills: o campo `when` vira um roteador curto, e o corpo só entra com
  `use_skill`. Relatório de subagente sem Status/Verificação, ou com PARTIAL/BLOCKED, é marcado e não conta como entrega.
- **Pontos de restauração**: antes de cada resposta o Órbita guarda uma foto da pasta do projeto (num git separado,
  sem mexer no seu). Depois da resposta aparece um cartão com os arquivos alterados, o diff colorido e os botões
  Desfazer e Refazer. Pode ser desligado em Configurações › Permissões.
- **`@arquivo`** no campo de mensagem: digite `@` para escolher um arquivo do projeto. O conteúdo vai junto da mensagem,
  então o agente não precisa procurar nem ler de novo.
- **Modo plano**: o botão Planejar faz o agente só ler e propor um plano. Tudo que alteraria algo fica bloqueado
  nesse turno. Depois é só clicar em Executar plano.
- Fechar um pedido de permissão com `Esc`, ou clicar em Parar, agora responde "não" em vez de deixar o agente travado
  esperando.
- **Atualizações pelo próprio programa**: o Órbita avisa quando há melhorias no GitHub e mostra as novidades e o que
  acontece com os arquivos. Atualizar agora fecha, atualiza e reabre sozinho. Conversas, configurações, chaves,
  memória, modelos e o ambiente Python nunca são tocados. O que é substituído ou removido ganha cópia de segurança.
  Pode ser desligado em Configurações › Sobre.
- **Linux**: o Órbita roda no Linux com `./iniciar_orbita.sh` (cria o ambiente e o atalho no menu de aplicativos). O
  terminal do agente usa bash, os programas abrem pelo menu do sistema, o volume usa PipeWire/PulseAudio e o agente
  sabe em que sistema está.
- **Partida e respostas mais rápidas**: bibliotecas pesadas (`httpx`, `asyncio`, geração de imagens) só são carregadas
  quando usadas, conexões HTTP são reaproveitadas e o roteamento/histórico usa cache em memória (inicialização ~40%
  mais rápida, tempo até o 1º token do motor de 854 ms para 28 ms e montagem por turno de 116 ms para 6 ms).

### Corrigido
- Configurações › Modelos: os modelos do provedor aparecem numa lista clicável (antes ficavam escondidos num campo de
  sugestões que sumia quando o campo tinha outro texto). A lista é buscada sozinha quando está vazia.
- Chave de API colada no lugar do nome do modelo (na API manual, no modelo principal, no perfil ou na primeira
  execução) agora é recusada com explicação. Quem já tinha salvo assim é corrigido sozinho ao abrir o programa: a
  chave sai das configurações e continua só no `.env`.
- Cancelar uma resposta enquanto o modelo já preparava chamadas de ferramenta não deixa mais chamadas incompletas no
  histórico da conversa (o que impedia continuar a mesma conversa nas APIs na nuvem).
- No modo de ferramentas por texto (`<tool_call>`), o filtro de streaming não engole mais os últimos caracteres da
  resposta quando há o símbolo `<` perto do fim (ex.: `2 < 3`).
- Links `file://` gerados em Markdown deixam de ser clicáveis, evitando abrir arquivos ou programas locais sem passar
  pelas permissões de execução.
- O aviso interno de limite de passos atingido agora é salvo com o marcador `(Sistema: ...)` para não reaparecer como
  mensagem do usuário ao reabrir a conversa.

## [0.1.0-alpha] — 2026-10-16

Primeira versão alfa pública.

### Recursos
- Agente com ferramentas (arquivos, PowerShell, web, controle do PC, memória, skills, imagens) que funciona com
  qualquer IA: Ollama local, APIs compatíveis com OpenAI (DeepSeek, GPT, Gemini, OpenRouter, Groq, xAI, Mistral,
  LM Studio, API manual com verificação de modelos), Claude pelo SDK oficial e Grok Build com a conta xAI.
- Modelos sem suporte a ferramentas funcionam pelo modo "ferramentas por prompt".
- Perfis com prompt de sistema, prompt inicial automático, modelo, pasta e ferramentas próprios; perfil
  ativado ao escolher um modelo.
- Equipe de subagentes em paralelo, cada um com seu modelo, com roteamento automático por especialidade e
  contratos de entrega (status, arquivos, verificação).
- Projeto de trabalho: abrir ou criar a pasta do projeto pela tela inicial ou pelo topo, com projetos recentes.
- MCP (stdio e HTTP) com ferramentas sob demanda — REA (engenharia reversa) incluído —, skills `SKILL.md` e plugins.
- Economia de tokens: modos máximo/equilibrado/livre, compactação inteligente do histórico, orçamento por tarefa
  e por dia com pausa para confirmar.
- Interface própria (identidade Órbita): conversas salvas, passos do agente em tempo real, painel ao vivo,
  notificações, paleta de comandos (Ctrl+K), assistente de primeira execução, tema claro/escuro, voz.

### Segurança
- Permissões por risco (`read`/`write`/`exec`) com modos Perguntar, Automático e Livre.
- HTML vindo de modelos sanitizado e Content-Security-Policy na interface; chaves só no `.env`.
- `verify_project` (roda pytest) classificada como execução; a verificação automática após a equipe pede
  permissão e roda uma única vez.
