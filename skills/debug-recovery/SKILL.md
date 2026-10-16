---
name: debug-recovery
description: Diagnóstico sistemático de erros, análise de stack traces/logs, isolamento de causa-raiz e recuperação de loops de ferramentas.
when: teste falho, exceção, ou a mesma ferramenta falhou duas vezes
---

# Debugging & Error Recovery (`debug-recovery`)

## Overview
Protocolo científico para diagnosticar bugs, falhas de testes, erros de provedores/MCP e loops de ferramentas. Proíbe "chutes" e edições às cegas: exige reprodução, isolamento da causa-raiz e teste de regressão.

## When to Use
- Quando um teste falha, um comando retorna exit code != 0 ou uma ferramenta lança exceção.
- Quando o detector de loop (`agent_loop.py`) alerta que uma chamada falhou 2 vezes.
- Ao investigar problemas em logs (`data/logs/agent.log` ou `data/logs/mcp-*.log`).

## Process

### 1. Coleta de Evidência Exata (Reproduce & Observe)
- Leia a mensagem de erro completa, stack trace ou últimas linhas de `data/logs/agent.log` (`read_file`).
- Reproduza a falha de forma isolada e rápida (ex.: `run_shell` com `pytest tests/test_x.py -k nome_do_teste -vv`).

### 2. Formulação e Isolamento de Hipótese (Root Cause)
- Localize o arquivo e linha exatos do ponto de falha com `read_file` e `grep`.
- Trace o fluxo de dados de trás para frente: qual entrada produziu o estado inválido?
- Formule **1 hipótese testável** por vez. Não altere 3 arquivos simultaneamente para "ver se resolve".

### 3. Mudança de Estratégia em Caso de Bloqueio (Loop Recovery)
Se uma ferramenta falhar 2 vezes com os mesmos argumentos:
1. **PARE** de chamar a mesma ferramenta do mesmo jeito.
2. Se `edit_file` falhou por `old_string não encontrado`: chame `read_file` nas linhas alvo para ver o conteúdo exato atual.
3. Se `run_shell` falhou por comando/caminho no Windows: verifique se falta `&` para caminhos com espaço, se o comando é cmd vs PowerShell, ou se o `cwd` existe.
4. Se um provedor/MCP falhou por credencial ou conexão: verifique `settings.py` / `.env` e informe o usuário objetivamente em vez de insistir.

### 4. Correção Mínima e Vacina (Regression Test)
- Aplique a correção na causa-raiz (não apenas no sintoma).
- Adicione ou ajuste um teste em `tests/` que falharia sem a correção.

## Common Rationalizations to Reject
- *"Vou tentar rodar o mesmo comando mais uma vez"* → Comandos determinísticos dão o mesmo erro. Mude os argumentos ou investigue o ambiente.
- *"Vou apagar/pular o teste que está falhando"* → Testes falhando revelam bugs reais ou contratos desatualizados. Corrija a causa, nunca esconda o teste.
- *"Deve ser problema de cache"* → Confirme antes com fatos; não culpe o ambiente sem evidência.

## Red Flags
- Repetir uma chamada de ferramenta idêntica após erro.
- Fazer múltiplas edições especulativas sem reexecutar o teste que falhou.
- Engolir exceções com `except Exception: pass` para fazer o erro sumir.

## Verification
1. O comando ou teste que antes falhava agora passa de forma reprodutível.
2. `verify_project` confirma que a correção não introduziu regressões em outros módulos.
