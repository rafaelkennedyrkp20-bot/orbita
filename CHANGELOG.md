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
- **Partida e respostas mais rápidas**: bibliotecas pesadas (`httpx`, `asyncio`, geração de imagens) só são carregadas
  quando usadas, conexões HTTP são reaproveitadas e o roteamento/histórico usa cache em memória (inicialização ~40%
  mais rápida, tempo até o 1º token do motor de 854 ms para 28 ms e montagem por turno de 116 ms para 6 ms).

### Corrigido
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
