import argparse
from pathlib import Path

from core import (
    SUPPORTED_EXTENSIONS,
    BatchEvent,
    ConversionOptions,
    ProgressEvent,
    convert_directory,
    convert_to_markdown,
    default_batch_output_root,
    ensure_environment,
    is_wsl_windows_mount,
    normalize_extensions,
    resolve_paths,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convierte documentos soportados por Docling a Markdown. "
        "Acepta un archivo o un directorio (procesa recursivamente PDFs)."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Archivo (PDF, DOCX, XLSX, PPTX, HTML) o directorio con PDFs a procesar.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Archivo de salida (modo archivo) o carpeta raíz de salida (modo batch). "
        "Default batch: <input>/markdowns",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="En modo batch: re-convierte aunque el .md de destino ya exista.",
    )
    parser.add_argument(
        "--ext",
        type=str,
        default="pdf",
        help=(
            "En modo batch: extensiones a procesar separadas por coma "
            "(default: pdf). Usá 'all' para todas las soportadas: "
            f"{sorted(SUPPORTED_EXTENSIONS)}. Ej: --ext pdf,docx,xlsx"
        ),
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


def _print_batch(event: BatchEvent) -> None:
    print(event.message)


def _run_single(args: argparse.Namespace, source: Path) -> None:
    source_path, output_path = resolve_paths(source, args.output)

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


def _run_batch(args: argparse.Namespace, root: Path) -> None:
    root = root.expanduser().resolve()
    output_root = (args.output or default_batch_output_root(root)).expanduser().resolve()

    if is_wsl_windows_mount(root):
        print(
            "⚠ Aviso: el path está en el filesystem de Windows (/mnt/...). "
            "La lectura va a ser mucho más lenta que desde el FS de WSL. "
            "Considerá copiar la carpeta a ~ antes de procesar."
        )

    options = ConversionOptions(
        chunk_size=args.chunk_size,
        max_retries=args.max_retries,
        do_ocr=args.ocr,
        table_mode=args.table_mode,
        num_threads=args.threads,
    )

    raw_exts = [e for e in (args.ext or "pdf").split(",") if e.strip()]
    extensions = normalize_extensions(raw_exts)

    print(f"Directorio raíz: {root}")
    print(f"Salida: {output_root}")
    print(f"Extensiones: {sorted(extensions)}")
    print(f"Force: {args.force}")
    print()

    summary = convert_directory(
        root,
        output_root,
        options=options,
        on_event=_print_batch,
        extensions=extensions,
        force=args.force,
    )

    print()
    print(
        f"Total: {summary['total']} | "
        f"Convertidos: {summary['converted']} | "
        f"Saltados: {summary['skipped']} | "
        f"Errores: {len(summary['errors'])}"
    )

    if summary["errors"]:
        print("\nArchivos con error:")
        for item in summary["errors"]:
            print(f"  - {item['file']}: {item['error']}")
        raise SystemExit(2)


def main() -> None:
    try:
        ensure_environment()
        args = parse_args()
        source = args.input.expanduser().resolve()

        if not source.exists():
            raise FileNotFoundError(f"No existe la ruta: {source}")

        if source.is_dir():
            _run_batch(args, source)
        else:
            _run_single(args, source)
    except Exception as e:
        print(f"Error en la ejecución: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
