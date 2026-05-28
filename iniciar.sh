#!/usr/bin/env bash
# Arranque rápido en macOS y Linux
# Uso: chmod +x iniciar.sh && ./iniciar.sh

set -e
cd "$(dirname "$0")"

echo
echo "================================================"
echo "  AGENTE INFO CLASIFICADOS - Iniciando..."
echo "================================================"
echo

# Buscar Python (python3 en Mac/Linux, python en Windows/WSL)
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERROR: Python no encontrado."
    echo "  macOS:  brew install python"
    echo "  Linux:  sudo apt install python3 python3-pip  (Debian/Ubuntu)"
    echo "          sudo dnf install python3 python3-pip  (Fedora)"
    exit 1
fi

echo "Usando: $($PY --version)"
echo
echo "Verificando dependencias..."
"$PY" -m pip install -q -r requirements.txt || {
    echo "Si pip da error de 'externally-managed-environment', prueba:"
    echo "  $PY -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
}

echo
echo "Iniciando servidor..."
echo "Se abrirá el navegador automáticamente en http://localhost:5790"
echo "Pulsa Ctrl+C para detener."
echo

"$PY" app.py
