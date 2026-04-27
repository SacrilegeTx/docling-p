@echo off
cd /d "%~dp0"
echo Iniciando Docling Markdown Converter...
echo Se abrira tu navegador automaticamente. Para detener, cerra esta ventana.
echo.
uv run python webapp.py
pause
