import argparse
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption


CHUNK_SIZE = 1
MAX_RETRIES = 2

# Entorno
load_dotenv()
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno requerida: {name}. "
            "Configurala en un archivo .env o en tu entorno."
        )
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convierte documentos soportados por Docling a Markdown."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Ruta del documento a convertir, por ejemplo PDF, DOCX, XLSX, PPTX o HTML.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Ruta donde se guardará el archivo Markdown. Si no se especifica, se guarda junto al archivo de entrada.",
    )
    return parser.parse_args()


def resolve_paths(input_path: Path, output_path: Path | None) -> tuple[Path, Path]:
    source_path = input_path.expanduser().resolve()

    if not source_path.exists():
        raise FileNotFoundError(f"No existe el archivo de entrada: {source_path}")

    if not source_path.is_file():
        raise ValueError(f"La ruta de entrada no es un archivo: {source_path}")

    resolved_output_path = output_path or source_path.with_suffix(".md")
    resolved_output_path = resolved_output_path.expanduser().resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)

    return source_path, resolved_output_path


def build_pdf_converter() -> DocumentConverter:
    # Este flujo está optimizado para PDFs born-digital con tablas grandes.
    # OCR queda desactivado porque en este proyecto ya provocó consumo excesivo
    # de memoria en RapidOCR sin aportar valor para documentos con texto real.
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True,
        mode=TableFormerMode.FAST,
    )
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=1,
        device=AcceleratorDevice.CPU,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


def write_chunk_pdf(
    reader: PdfReader, start_page: int, end_page: int, chunk_path: Path
) -> None:
    writer = PdfWriter()
    for page_num in range(start_page, end_page):
        writer.add_page(reader.pages[page_num])

    with open(chunk_path, "wb") as f:
        writer.write(f)


def convert_chunk_with_retries(
    converter: DocumentConverter,
    chunk_path: Path,
    page_label: str,
    max_retries: int,
) -> str:
    last_error = None

    for attempt in range(1, max_retries + 2):
        try:
            result = converter.convert(str(chunk_path))
            return result.document.export_to_markdown() + "\n\n"
        except Exception as e:
            last_error = e
            if attempt <= max_retries:
                print(f"Intento {attempt} falló para {page_label}: {e}. Reintentando...")
            else:
                print(f"Intento final falló para {page_label}: {e}")

    raise RuntimeError(
        f"No se pudo convertir {page_label} después de {max_retries} reintentos."
    ) from last_error


def convert_pdf_to_markdown(source_path: Path, output_path: Path) -> None:
    tmp_dir = Path("tmp")
    incremental_output_path = tmp_dir / f"{source_path.stem}.partial.md"
    converter = build_pdf_converter()

    try:
        tmp_dir.mkdir(exist_ok=True)
        incremental_output_path.write_text("", encoding="utf-8")

        reader = PdfReader(source_path)
        total_pages = len(reader.pages)

        print(f"Total de páginas: {total_pages}. Procesando en bloques de {CHUNK_SIZE}...")

        for i in range(0, total_pages, CHUNK_SIZE):
            upper_bound = min(i + CHUNK_SIZE, total_pages)
            print(f"--- Procesando páginas {i + 1} a {upper_bound} ---")
            temp_chunk_path = tmp_dir / f"chunk_{i + 1:04d}_{upper_bound:04d}.pdf"

            try:
                write_chunk_pdf(reader, i, upper_bound, temp_chunk_path)
                markdown_chunk = convert_chunk_with_retries(
                    converter=converter,
                    chunk_path=temp_chunk_path,
                    page_label=f"páginas {i + 1} a {upper_bound}",
                    max_retries=MAX_RETRIES,
                )

                with open(incremental_output_path, "a", encoding="utf-8") as f:
                    f.write(markdown_chunk)
            finally:
                if temp_chunk_path.exists():
                    temp_chunk_path.unlink()

        shutil.copyfile(incremental_output_path, output_path)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def convert_document_to_markdown(source_path: Path, output_path: Path) -> None:
    converter = DocumentConverter()
    result = converter.convert(str(source_path))
    output_path.write_text(result.document.export_to_markdown() + "\n", encoding="utf-8")


def main() -> None:
    try:
        os.environ["HF_TOKEN"] = require_env("HF_TOKEN")
        args = parse_args()
        source_path, output_path = resolve_paths(args.input, args.output)

        print(f"Archivo de entrada: {source_path}")
        print(f"Archivo de salida: {output_path}")

        if source_path.suffix.lower() == ".pdf":
            convert_pdf_to_markdown(source_path, output_path)
        else:
            convert_document_to_markdown(source_path, output_path)

        print(f"\n¡Éxito! Archivo guardado en: {output_path}")
    except Exception as e:
        print(f"Error en la ejecución: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
