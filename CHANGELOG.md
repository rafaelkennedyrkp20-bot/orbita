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
- Agentes de pesquisa (perfil com especialidade "pesquisa" e acesso à web, como o Pesquisador) passam a receber o
  protocolo "Descobrir o melhor agente" e a lista dos modelos com acesso: pesquisam fontes atuais, recomendam o
  melhor modelo disponível e uma alternativa, e oferecem a configuração sem alterar nada sozinhos.

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
