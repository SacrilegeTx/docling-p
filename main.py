import argparse
import os
import re
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


from lxml import etree

_FENCED_BLOCK_RE = re.compile(r"```([^\n]*)\n(.*?)\n```", re.DOTALL)
_ROW_MARKER_RE = re.compile(r"(?<!\S)(\d+(?:\s+\d+)*)\s+(?=[A-ZÁÉÍÓÚÑ])")
_TABLE_BLOCK_GUARD_RE = re.compile(r"^\s*(?:\d+\s+)+[A-ZÁÉÍÓÚÑ]")
_XML_DECL_RE = re.compile(r"^\s*<\?xml[^?]*\?>\s*", re.DOTALL)


def _is_inside_xml_tag(text: str, pos: int) -> bool:
    return text.rfind("<", 0, pos) > text.rfind(">", 0, pos)


def restructure_xml_table_block(content: str) -> str | None:
    # Cuando docling no logra detectar una tabla de la forma
    # "número | descripción | XML", la aplasta a un único CodeItem con todas
    # las filas concatenadas en una sola línea. Detectamos ese patrón y la
    # re-segmentamos por número de fila para preservar el mapping fila ↔ XML
    # y dejar cada ejemplo como bloque buscable con `rg`.
    if not _TABLE_BLOCK_GUARD_RE.match(content):
        return None
    if "<" not in content:
        return None

    matches = [
        m
        for m in _ROW_MARKER_RE.finditer(content)
        if not _is_inside_xml_tag(content, m.start())
    ]
    if len(matches) < 2:
        return None

    out: list[str] = []
    for i, m in enumerate(matches):
        nums = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[body_start:body_end].strip()

        xml_at = body.find("<")
        if xml_at == -1:
            description, xml = body, ""
        else:
            description = body[:xml_at].strip()
            xml = body[xml_at:].strip()

        is_group = " " in nums
        label = (
            f"Filas {', '.join(nums.split())}" if is_group else f"Fila {nums}"
        )
        heading_desc = description[:80].rstrip(" ,.;:")
        if len(description) > 80:
            heading_desc += "…"

        out.append(f"### {label} — {heading_desc}")
        out.append("")
        if description:
            out.append(description)
            out.append("")
        if xml:
            out.append("```xml")
            out.append(xml)
            out.append("```")
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def denormalize_flattened_tables(md: str) -> str:
    def replace(match: re.Match[str]) -> str:
        restructured = restructure_xml_table_block(match.group(2))
        return restructured if restructured is not None else match.group(0)

    return _FENCED_BLOCK_RE.sub(replace, md)


def _looks_like_xml(content: str) -> bool:
    stripped = content.lstrip()
    if not stripped.startswith("<"):
        return False
    return "</" in stripped or "/>" in stripped


def _regex_pretty_print_xml(xml: str, indent: str = "  ") -> str:
    # Fallback usado cuando lxml no logra recuperar nada del fragmento.
    text = re.sub(r"\s+", " ", xml).strip()
    text = re.sub(r">\s*<", ">\n<", text)

    out: list[str] = []
    depth = 0
    same_line_pair_re = re.compile(r"^<[^/!?][^>]*>[^<]*</[^>]+>\s*$")

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("</"):
            depth = max(0, depth - 1)
            out.append(indent * depth + line)
        elif (
            line.startswith("<?")
            or line.startswith("<!")
            or line.endswith("/>")
            or same_line_pair_re.match(line)
        ):
            out.append(indent * depth + line)
        elif line.startswith("<"):
            out.append(indent * depth + line)
            depth += 1
        else:
            out.append(indent * depth + line)

    return "\n".join(out)


def pretty_print_xml(content: str, indent: str = "  ") -> str:
    # Los ejemplos XML emitidos por docling suelen venir aplastados en una
    # sola línea. Los parseamos con lxml en modo recovering — los fragmentos
    # no siempre tienen un único root, así que envolvemos en un wrapper
    # sintético y dedent-amos el resultado. Si lxml no recupera nada
    # (típicamente por artefactos de OCR muy rotos) caemos al fallback regex
    # que es tolerante por construcción.
    text = content.strip()
    if not text:
        return content

    decl_match = _XML_DECL_RE.match(text)
    decl = decl_match.group(0).strip() if decl_match else ""
    body = text[decl_match.end():] if decl_match else text

    wrapped = f"<__docling_wrap__>{body}</__docling_wrap__>"
    parser = etree.XMLParser(recover=True, remove_blank_text=True)

    try:
        root = etree.fromstring(wrapped.encode("utf-8"), parser)
    except etree.XMLSyntaxError:
        return _regex_pretty_print_xml(content, indent)

    if root is None or (len(root) == 0 and not (root.text or "").strip()):
        return _regex_pretty_print_xml(content, indent)

    etree.indent(root, space=indent)
    full = etree.tostring(root, encoding="unicode", pretty_print=True)

    lines = full.split("\n")
    if len(lines) < 2:
        return _regex_pretty_print_xml(content, indent)

    inner = lines[1:-1] if lines[-1].strip() == "" else lines[1:]
    if inner and inner[-1].strip().startswith("</__docling_wrap__"):
        inner = inner[:-1]
    inner = [l[len(indent):] if l.startswith(indent) else l for l in inner]

    parts: list[str] = []
    if decl:
        parts.append(decl)
    parts.extend(inner)
    return "\n".join(parts).rstrip()


def format_xml_blocks(md: str) -> str:
    def replace(match: re.Match[str]) -> str:
        lang = match.group(1).strip()
        content = match.group(2)
        if not _looks_like_xml(content):
            return match.group(0)
        formatted = pretty_print_xml(content)
        out_lang = lang or "xml"
        return f"```{out_lang}\n{formatted}\n```"

    return _FENCED_BLOCK_RE.sub(replace, md)


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
            md = result.document.export_to_markdown()
            md = denormalize_flattened_tables(md)
            md = format_xml_blocks(md)
            return md + "\n\n"
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
    md = result.document.export_to_markdown()
    md = denormalize_flattened_tables(md)
    md = format_xml_blocks(md)
    output_path.write_text(md + "\n", encoding="utf-8")


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
