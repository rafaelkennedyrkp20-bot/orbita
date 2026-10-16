---
name: code-review-simplify
description: Revisão adversarial de código focada em bugs reais, segurança, concorrência, eliminação de bloat/código morto e simplificação estrutural.
---

# Code Review & Simplification (`code-review-simplify`)

## Overview
Executa revisão técnica rigorosa (nível Staff Engineer) para encontrar bugs concretos, vulnerabilidades de segurança, problemas de concorrência e complexidade acidental (bloat), propondo ou aplicando simplificações diretas.

## When to Use
- Após implementar mudanças relevantes ou receber resultados de subagentes (`delegate_task`).
- Quando o perfil ativo for `revisor` ou `lider_dev`.
- Antes de fechar uma fase do `ROADMAP.md`.
- Quando o usuário pedir auditoria, code review, refatoração ou enxugamento de código.

## Process

### 1. Mapeamento do Diff e Superfície de Impacto
- Identifique todos os arquivos modificados (`run_shell` com `git status` e `git diff`, ou `read_file`).
- Leia os chamadores (`grep`) de qualquer função cuja assinatura ou retorno tenha mudado.

### 2. Checklist Adversarial (Caça a Bugs Reais)
Avalie cada mudança contra estas 5 categorias (ignore estilo cosmético):
1. **Quebra de Contrato / Tipos**: Retornos `None` não tratados, chaves ausentes em `dict`, exceções engolidas silenciosamente.
2. **Concorrência e Bloqueio**: Chamadas de rede/disco na thread da GUI (`agent/gui.py`), estado compartilhado sem `threading.Lock`, ferramentas MCP chamadas em paralelo.
3. **Segurança e Fronteiras**:
   - Injeção de comando ou path traversal fora do workspace.
   - Vazamento de chaves de API em logs ou JSONs persistidos.
   - HTML não sanitizado indo para a interface web (`render.markdown_html` / `esc()`).
4. **Orçamento de Contexto**: Loops que acumulam mensagens gigantes sem truncamento, payloads brutos sem limite de caracteres.
5. **Anti-Bloat / Simplificação**:
   - Código morto, variáveis/imports não usados, abstrações prematuras para um único caso de uso.
   - Funções duplicadas que podem ser consolidadas em uma só.

### 3. Classificação e Ação
Classifique cada achado com evidência (`arquivo:linha` + cenário exato de falha):
- **[P0 - Crítico]**: Bug funcional, crash, perda de dados ou falha de segurança → **Corrija imediatamente**.
- **[P1 - Importante]**: Borda não tratada, código morto ou risco de performance/contexto → **Simplifique/corrija**.
- **[P2 - Opcional]**: Sugestão menor → Registre em 1 linha sem inflar o escopo.

## Common Rationalizations to Reject
- *"Pode ser útil no futuro"* → Se não é usado agora, é código morto. Remova.
- *"Vou adicionar um try/except Exception: pass para evitar crash"* → Mascarar erros impede o agente de se auto-corrigir. Retorne `ToolResult.error(...)` ou logue com contexto claro.
- *"Parece funcionar pelo código"* → "Parece bom" não conta. Verifique com `verify_project` e testes de borda.

## Red Flags
- Relatórios de revisão genéricos ("o código está bem estruturado") sem apontar linhas e fluxos reais.
- Manter código antigo comentado ou funções depreciadas sem chamadores.
- Aumentar o número total de linhas em uma tarefa de refatoração/simplificação sem justificativa forte.

## Verification
1. Rode `verify_project` para garantir 0 avisos do `pyflakes` e 100% dos testes passando.
2. Confirme com `grep` que símbolos removidos ou renomeados não deixaram referências órfãs.
