import argparse
from pathlib import Path

from core import (
    ConversionOptions,
    ProgressEvent,
    convert_to_markdown,
    ensure_environment,
    resolve_paths,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convierte documentos soportados por Docling a Markdown."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Ruta del documento a convertir (PDF, DOCX, XLSX, PPTX o HTML).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Ruta de salida. Por defecto: junto al archivo de entrada.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1,
        help="Páginas por bloque al procesar PDFs (default: 1).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Reintentos por bloque ante errores (default: 2).",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Habilita OCR. Costoso en RAM; usar solo con PDFs escaneados.",
    )
    parser.add_argument(
        "--table-mode",
        choices=("fast", "accurate"),
        default="fast",
        help="Modo de detección de tablas (default: fast).",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="Threads para el acelerador CPU (default: 1).",
    )
    return parser.parse_args()


def _print_progress(event: ProgressEvent) -> None:
    if event.kind == "page_start":
        print(f"--- {event.message} ---")
    elif event.kind in ("page_done", "done"):
        return
    else:
        print(event.message)


def main() -> None:
    try:
        ensure_environment()
        args = parse_args()
        source_path, output_path = resolve_paths(args.input, args.output)

        options = ConversionOptions(
            chunk_size=args.chunk_size,
            max_retries=args.max_retries,
            do_ocr=args.ocr,
            table_mode=args.table_mode,
            num_threads=args.threads,
        )

        print(f"Archivo de entrada: {source_path}")
        print(f"Archivo de salida: {output_path}")

        convert_to_markdown(
            source_path,
            output_path,
            on_progress=_print_progress,
            options=options,
        )

        print(f"\n¡Éxito! Archivo guardado en: {output_path}")
    except Exception as e:
        print(f"Error en la ejecución: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
