---
name: descobrir-agente
description: Pesquisa fontes atuais e recomenda o melhor modelo, IA ou servidor MCP para uma tarefa, comparando com o que o usuário já tem acesso. Não configura nada.
when: escolher o melhor modelo, IA, servidor MCP ou ferramenta para uma tarefa
context: models
---

# Descobrir o melhor agente (`descobrir-agente`)

## Overview
Recomenda modelo, IA ou servidor MCP com fonte atual e com o que já está configurado. A tabela de modelos com acesso vem anexada a esta skill; o que não está nela não está disponível.

## When to Use
- O usuário pergunta qual o melhor modelo, IA, agente ou ferramenta para uma tarefa.
- Precisa comparar custo, qualidade, privacidade ou local × nuvem antes de escolher.
- Quer um servidor MCP e o comando para instalá-lo depois.

## Process
1. Entenda a tarefa e os critérios (qualidade, custo, privacidade, local × nuvem).
2. Pesquise fontes atuais com `web_search` (`read_pages=true`) e `fetch_url`: benchmarks, comparativos, documentação e repositórios oficiais. Cite título, URL e data. Separe fato de palpite e diga quando a fonte for fraca ou antiga.
3. Compare com a tabela anexada. Recomende primeiro o melhor que já está disponível, depois uma alternativa, com custo e o que falta para usá-la.
4. Para servidor MCP: prefira repositório oficial ou autor conhecido. Informe comando, variáveis de ambiente e o risco (MCP executa código no computador).
5. NÃO configure nem instale nada. Termine oferecendo a configuração e mostre o passo exato: chave no `.env`, trecho para `data/mcp.json`, ou troca em Configurações › Modelos. O usuário decide.

## Common Rationalizations to Reject
- *"Já sei qual é o melhor, não preciso pesquisar"* → Ranking de modelo muda. Sem fonte com data, a recomendação é palpite.
- *"Vou já gravar a chave / o mcp.json para adiantar"* → Configurar e instalar MCP executa código e muda a conta do usuário. Só mostre o passo.

## Red Flags
- Recomendar como disponível um modelo que não está na tabela anexada.
- Citar benchmark sem URL.
- Instalar servidor MCP ou editar `.env` nesta skill.

## Verification
1. A resposta cita pelo menos uma fonte (título + URL) ou diz explicitamente que a busca não retornou fonte utilizável.
2. A recomendação principal está na tabela de modelos com acesso, ou está marcada como alternativa ainda não configurada.
3. Nenhum arquivo de configuração foi alterado.
