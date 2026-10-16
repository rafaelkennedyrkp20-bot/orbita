#!/usr/bin/env bash
# Órbita no Linux/macOS: prepara o ambiente na primeira vez, cria o atalho no menu e abre o programa.
# Uso: ./iniciar_orbita.sh   (ou: ./iniciar_orbita.sh --check para só verificar)
set -u
cd "$(dirname "$0")" || exit 1

PY=""
for candidate in python3.12 python3.13 python3.11 python3.14 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "Python 3.10 a 3.14 não foi encontrado."
    echo "Debian/Ubuntu: sudo apt install python3 python3-venv"
    echo "Fedora:        sudo dnf install python3"
    echo "Arch:          sudo pacman -S python"
    exit 1
fi

"$PY" launcher.py "$@"
status=$?
if [ "$status" -ne 0 ]; then
    echo
    echo "O Órbita não iniciou. Veja data/logs/agent.log ou rode: ./iniciar_orbita.sh --check"
fi
exit "$status"
