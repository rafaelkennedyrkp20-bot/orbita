---
name: spec-plan-tdd
description: Fluxo estruturado de especificação enxuta, decomposição de tarefas com critérios de aceite e implementação incremental guiada por testes (TDD) e gates de verificação.
---

# Spec, Plan & Incremental TDD (`spec-plan-tdd`)

## Overview
Transforma pedidos ambíguos ou mudanças não-triviais (>1 arquivo, mudança de arquitetura ou nova feature) em entregas determinísticas, enxutas e 100% verificadas. Substitui "tentativa e erro" pelo ciclo **DEFINE → PLAN → BUILD → VERIFY**.

## When to Use
- Qualquer mudança que afete mais de 1 arquivo ou altere contratos/interfaces.
- Criação de novas ferramentas, provedores, skills ou fluxos de orquestração.
- Refatorações onde o comportamento externo deve permanecer intacto.
- Quando o usuário pedir planejamento, arquitetura ou alta confiabilidade.

## Process

### 1. DEFINE (Especificação Mínima)
Antes de escrever código, mapeie com `read_file` / `grep` / `glob_files`:
- **Objetivo**: O que muda no comportamento observável (1-2 frases).
- **Arquivos-alvo**: Lista exata de arquivos a modificar (prefira editar existentes a criar novos).
- **Invariantes / Limites**: O que NÃO pode quebrar (compatibilidade, encoding, thread-safety, orçamento de tokens).
- **Critérios de Aceite (AC)**: Condições binárias (Passa/Falha) verificáveis por comando ou teste.

### 2. PLAN (Decomposição Atômica)
Divida em até 3-5 passos ordenados por dependência:
1. Preparar teste ou contrato que reproduz/valida o requisito.
2. Implementar a mudança mínima no núcleo.
3. Rodar verificação rápida (`verify_project` ou `pytest -k`).
4. Limpar código morto/redundâncias introduzidas.

### 3. BUILD (Implementação Cirúrgica)
- Use `edit_file` com contexto suficiente para substituição única.
- Evite adicionar dependências externas, classes wrapper desnecessárias ou flags de configuração não pedidas.
- Se a subtarefa for independente e paralelizável em módulos distintos, use `delegate_task` passando `files`, `acceptance_criteria` e `verify_cmd`.

### 4. VERIFY (Gate Obrigatório)
Chame `verify_project` (ou `run_shell` com `pytest` e `pyflakes`):
- Verifique se o novo teste falha sem a mudança (ou testa especificamente a borda crítica) e passa com ela.
- Confira se há warnings de sintaxe, imports não usados (`pyflakes`) ou regressões na suíte global.

## Common Rationalizations to Reject
- *"A mudança é simples, não preciso rodar os testes agora"* → Mudanças "simples" quebram imports e contratos silenciosamente. Rode `verify_project`.
- *"Vou criar um arquivo novo para não mexer no existente"* → Isso gera bloat e fragmentação. Consolide no módulo existente.
- *"O teste existente já cobre isso indiretamente"* → Se você adicionou lógica condicional nova, adicione uma asserção explícita para ela.

## Red Flags
- Editar arquivos sem antes lê-los com `read_file`.
- Mais de 2 edições seguidas no mesmo arquivo sem rodar verificação.
- Adicionar >100 linhas quando 20 linhas resolvem o problema.
- Declarar tarefa concluída com testes falhando ou não executados.

## Verification
Uma execução sob esta skill só termina quando:
1. `verify_project` retorna status `PASS` (`pyflakes` = 0 erros e `pytest` = 0 falhas).
2. Todos os Critérios de Aceite definidos no passo 1 foram comprovados com saída real de ferramenta.
