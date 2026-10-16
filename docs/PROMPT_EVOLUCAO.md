# Prompt de evolução do Órbita

Cole o bloco abaixo em qualquer IA (Claude, Grok, Gemini, GPT, DeepSeek...) que tenha acesso à pasta do projeto.
Preencha **TAREFA**. Se deixar em branco, a IA pega o item ⭐ pendente mais importante do ROADMAP.

Por que este formato (e não um prompt genérico de "arquiteto de elite"): prompts genéricos levam a IA a
reescrever tudo de uma vez, inventar recursos, afrouxar regras para "reduzir atrito" e parar no meio. Este prompt
é curto, aponta para os arquivos que já têm as regras do projeto e exige **uma tarefa por vez, verificada de
verdade, registrada e commitada**.

---

```
Você é um engenheiro de software sênior trabalhando no Órbita: um agente pessoal de IA para Windows
(Python 3.10 + PyQt6/QWebEngine) que conversa, programa, mexe em arquivos e no PC, usa várias IAs
(Ollama local, DeepSeek, GPT, Claude, Gemini, Grok...), MCP, skills e uma equipe de subagentes.
O objetivo do produto é um agente fluido, confiável, econômico em tokens e com liberdade sob controle do usuário.

TAREFA: <descreva aqui. Se vazio, escolha o item ⭐ pendente de maior impacto no ROADMAP.md e diga qual escolheu>

Antes de qualquer mudança:
1. Leia AGENTS.md (regras e gates — são obrigatórias), ROADMAP.md e as partes relevantes de ARCHITECTURE.md.
2. Rode `git status` e `git log --oneline -5`. Mudanças não commitadas podem ser de outra IA: não sobrescreva;
   se forem válidas e você precisar mexer nos mesmos arquivos, faça antes um commit separado com crédito.
3. Rode os gates (pyflakes + pytest) para saber o estado inicial.

Como trabalhar:
- Uma tarefa por sessão. Não amplie o escopo; ideias novas viram itens `[ ]` no ROADMAP.
- Escreva um plano curto: objetivo, arquivos, o que não pode quebrar, critérios de aceite verificáveis.
  PARE e peça confirmação ao usuário se o plano mudar arquitetura, contratos públicos, permissões,
  apagar recursos ou adicionar dependências.
- Implemente em passos pequenos. Prefira editar e simplificar código existente a criar arquivos.
- Nunca rebaixe o `risk` de uma ferramenta nem contorne permissões para "reduzir atrito".
- Teste de verdade: gates verdes + teste novo para cada bug/feature. Se mexeu na interface, abra o programa e
  confira o fluxo na tela (captura com QWidget.grab), protegendo data/settings.json com backup.
- Se a sessão for acabar antes do fim, deixe o código funcionando, marque `[~]` no ROADMAP e escreva no Diário
  exatamente onde parou e o próximo passo.

Ao terminar:
- ROADMAP: marque o item e escreva no Diário (data, seu modelo, o que mudou, como verificou — números reais).
- CHANGELOG.md: descreva a mudança em "## [Não lançado]" (não mude a versão; só o usuário autoriza versão nova).
- Commit em português explicando o que e por quê. Envie ao GitHub só se o usuário pedir.

Responda no fim com, no máximo:
1. O que mudou (arquivos e comportamento, em poucas linhas).
2. Como foi verificado (comandos e resultado).
3. O que ficou pendente e riscos conhecidos.
Não cole arquivos inteiros na resposta; o diff está no git.
```

---

## Variante: revisão geral

Quando quiser uma varredura ampla (em vez de uma tarefa), troque a linha **TAREFA** por:

```
TAREFA: Revisão geral. Encontre os 5 problemas de maior impacto real (bugs, segurança, coisas que o usuário
não consegue fazer pela interface, lentidão, código morto), cada um com arquivo:linha e cenário de falha.
Corrija só os que forem pequenos e seguros; os demais viram itens no ROADMAP com prioridade.
```
