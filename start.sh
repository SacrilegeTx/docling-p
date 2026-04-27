#!/bin/sh
cd "$(dirname "$0")"
echo "Iniciando Docling Markdown Converter..."
echo "Se abrirá tu navegador automáticamente. Ctrl+C para detener."
echo
exec uv run python webapp.py
