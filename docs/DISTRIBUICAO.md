# Distribuição do Órbita — base LU-18

## Contrato desta etapa

Objetivo: executar os gates em CI Windows/Linux e produzir um protótipo desktop sem
carregar configurações, chaves, conversas, memória ou pesos da máquina que compila.
Arquivos: workflow, `scripts/build_package.py`, `packaging/orbita_entry.py`,
`agent/core/config.py`, `requirements-build.txt` e `tests/test_packaging.py`.
Invariantes: versão e tags não mudam; instalação por fonte continua funcionando;
recursos empacotados são somente leitura, dados novos pertencem ao usuário.
Aceite desta base: gates locais verdes; manifesto inspecionável; recursos públicos
incluídos por lista permitida e testes de travessia/links; smoke test Windows real.
LU-18 integral ainda depende de instalador, Linux real e canal autenticado.

## CI

`.github/workflows/tests.yml` executa pyflakes e toda a suíte pytest em Windows e
Ubuntu, com Python 3.10 e 3.12. A interface Qt roda com plataforma `offscreen` e
Chromium sem GPU; não depende de microfone, Ollama ou chave de nuvem. `ORBITA_HOME`
aponta para diretório temporário do runner. O workflow não publica artefatos e
possui somente permissão de leitura do repositório. O primeiro resultado remoto
precisa ser conferido no Actions; testes locais não substituem a matriz remota.

## Compilar e inspecionar

Compile separadamente em cada sistema: PyInstaller não gera Linux a partir do
Windows. Use ambiente virtual limpo, com as dependências do projeto e de build:

```powershell
python -m venv temp/build-venv
temp/build-venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-build.txt
temp/build-venv/Scripts/python.exe scripts/build_package.py --manifest-only
temp/build-venv/Scripts/python.exe scripts/build_package.py
```

No Linux, substitua `Scripts/python.exe` por `bin/python`. Qt WebEngine exige as
bibliotecas gráficas/áudio de sistema; a CI lista as dependências Ubuntu. O
resultado fica em `temp/package/dist/Orbita/`, com executável e `_internal`.
Distribua a pasta inteira; copiar só o executável perde o Chromium e os recursos.
O build não instala dependências automaticamente e não remove diretórios existentes.
Para recompilar, use `--output temp/package-novo`.

O manifesto `components.json` contém componentes presentes/ausentes e SHA-256 de
cada recurso público. Web usa cinco arquivos explícitos; skills aceitam somente
Markdown/Python rastreados no git; o catálogo tem o caminho fixo
`agent/core/local_models.json`. Arquivos ocultos, diretórios de dados/modelos/
ambiente, links e caminhos que saem da árvore são recusados ou excluídos.
Código do agente é coletado pelo analisador Python, sem cópia genérica do projeto.
Não adicionar chaves a código ou documentação: a lista permitida de extensões não
consegue detectar um segredo colado dentro de um arquivo público.

## Dados e opcionais

Em execução por fonte, o diretório de dados continua na raiz do projeto. Definir
`ORBITA_HOME` escolhe outra raiz explicitamente. No pacote, o padrão é
`%LOCALAPPDATA%/Orbita` no Windows ou `$XDG_DATA_HOME/orbita` no Linux (fallback
`~/.local/share/orbita`). `.env`, `data/`, `models/` e memória ficam sob essa raiz;
o `.env` junto dos recursos internos não é lido. Preferências existentes não são
reescritas pelo import da configuração. Recursos de interface usam `__file__`;
skills embutidas devem usar `RESOURCE_ROOT`, plugins usam a raiz gravável.

O protótipo desktop exclui motores locais Whisper/Kokoro, CUDA e PyTorch para
evitar empacotar vários GB. Ollama e ComfyUI continuam servidores independentes.
Pesos e servidores não são baixados ao iniciar. Voz local completa continua
disponível pela instalação por fonte; instalar pacotes com pip não estende o
interpretador congelado. Não anunciar o pacote como instalador completo de voz.

## Verificação e limites

```powershell
$env:ORBITA_HOME = 'E:/IA/AgentePessoal/temp/package-smoke'
Start-Process -FilePath 'temp/package/dist/Orbita/Orbita.exe' -ArgumentList '--package-check' -Wait -WindowStyle Hidden
Get-Content temp/package-smoke/package-check.json
```

O smoke importa Qt/WebEngine, verifica recursos e registra os caminhos sem criar
settings nem chamar provedores. Em Linux execute `Orbita --package-check` com
`ORBITA_HOME` temporário. Uma abertura visual e uma conversa real ainda são
necessárias antes de publicar um instalador.

Subprocessos internos `-m agent.actions.web_check` e `-m agent.core.grok_bridge`
são despachados pelo entrypoint. O executável não é Python genérico; tarefas de
programação/testes precisam de Python externo. `apply()` recusa quando o processo
está congelado (`sys.frozen`), antes de baixar ou gravar, e não mexe em conversas,
chaves nem modelos. A verificação `--package-check` não cobre funções externas
como git, Blender, ffmpeg ou servidores MCP.

## Canal com chave compartilhada

`apply_verified` confere um HMAC-SHA256 do manifesto antes de gravar qualquer
arquivo. A chave não fica no repositório: vem de `ORBITA_UPDATE_KEY` ou do
arquivo em `ORBITA_UPDATE_KEY_FILE`. Sem chave, com o selo errado ou com um hash
que não bate, nada muda e nenhuma pasta `data/updates/backup-*` é criada.
Caminhos protegidos (`data/`, `.env`, `venv/`, `models/` e a memória antiga)
são ignorados mesmo se o manifesto os listar. Se a gravação quebra no meio, os
arquivos novos saem e os anteriores voltam; a restauração também recusa caminho
protegido. O hash conferido é o SHA-256 dos bytes, não o hash de blob do git.

Isso é uma chave compartilhada, não uma assinatura de chave pública. Hashes
sozinhos detectam alteração acidental e não provam quem publicou o pacote. O
botão de atualização do GitHub segue `git pull` ou o ZIP público, sem esse selo,
porque não há chave publicada. O manifesto do protótipo continua
`unsigned-development-build`.

Para fechar LU-18 ainda faltam o instalador, a validação Linux real e um
processo de chave pública. Não criar uma chave pública fictícia nem declarar
esse canal autenticado.

Referências primárias consultadas: [PyInstaller: informações em execução](https://pyinstaller.org/en/stable/runtime-information.html)
e [opções de compilação](https://pyinstaller.org/en/stable/usage.html).
