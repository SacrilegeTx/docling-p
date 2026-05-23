import hashlib
import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from lxml import etree
from pypdf import PdfReader, PdfWriter

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption


load_dotenv()
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


TABLE_MODES = {"fast": TableFormerMode.FAST, "accurate": TableFormerMode.ACCURATE}


@dataclass(frozen=True)
class ConversionOptions:
    chunk_size: int = 1
    max_retries: int = 2
    do_ocr: bool = False
    table_mode: str = "fast"
    num_threads: int = 1

    def __post_init__(self) -> None:
        if self.chunk_size < 1:
            raise ValueError("chunk_size debe ser >= 1")
        if self.max_retries < 0:
            raise ValueError("max_retries debe ser >= 0")
        if self.table_mode not in TABLE_MODES:
            raise ValueError(
                f"table_mode debe ser uno de {list(TABLE_MODES)}, recibido: {self.table_mode}"
            )
        if self.num_threads < 1:
            raise ValueError("num_threads debe ser >= 1")


DEFAULT_OPTIONS = ConversionOptions()


@dataclass
class ProgressEvent:
    kind: str
    message: str
    current: int | None = None
    total: int | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def _noop_progress(_: ProgressEvent) -> None:
    pass


def ensure_environment() -> None:
    token = os.getenv("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "Falta la variable de entorno requerida: HF_TOKEN. "
            "Configurala en un archivo .env o en tu entorno."
        )
    os.environ["HF_TOKEN"] = token


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


def build_pdf_converter(options: ConversionOptions) -> DocumentConverter:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = options.do_ocr
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True,
        mode=TABLE_MODES[options.table_mode],
    )
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=options.num_threads,
        device=AcceleratorDevice.CPU,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


_FENCED_BLOCK_RE = re.compile(r"```([^\n]*)\n(.*?)\n```", re.DOTALL)
_ROW_MARKER_RE = re.compile(r"(?<!\S)(\d+(?:\s+\d+)*)\s+(?=[A-ZÁÉÍÓÚÑ])")
_TABLE_BLOCK_GUARD_RE = re.compile(r"^\s*(?:\d+\s+)+[A-ZÁÉÍÓÚÑ]")
_XML_DECL_RE = re.compile(r"^\s*<\?xml[^?]*\?>\s*", re.DOTALL)


def _is_inside_xml_tag(text: str, pos: int) -> bool:
    return text.rfind("<", 0, pos) > text.rfind(">", 0, pos)


def restructure_xml_table_block(content: str) -> str | None:
    # Cuando docling no logra detectar una tabla "número | descripción | XML",
    # la aplasta a un único CodeItem con todas las filas concatenadas en una
    # sola línea. Detectamos ese patrón y la re-segmentamos por número de fila
    # para preservar el mapping fila ↔ XML y dejar cada ejemplo como bloque
    # buscable con `rg`.
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
    on_progress: ProgressCallback,
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
                on_progress(ProgressEvent(
                    kind="retry",
                    message=f"Intento {attempt} falló para {page_label}: {e}. Reintentando...",
                ))
            else:
                on_progress(ProgressEvent(
                    kind="warning",
                    message=f"Intento final falló para {page_label}: {e}",
                ))

    raise RuntimeError(
        f"No se pudo convertir {page_label} después de {max_retries} reintentos."
    ) from last_error


def convert_pdf_to_markdown(
    source_path: Path,
    output_path: Path,
    options: ConversionOptions,
    on_progress: ProgressCallback,
) -> None:
    tmp_dir = Path("tmp")
    incremental_output_path = tmp_dir / f"{source_path.stem}.partial.md"
    converter = build_pdf_converter(options)

    try:
        tmp_dir.mkdir(exist_ok=True)
        incremental_output_path.write_text("", encoding="utf-8")

        reader = PdfReader(source_path)
        total_pages = len(reader.pages)

        on_progress(ProgressEvent(
            kind="info",
            message=f"Total de páginas: {total_pages}. Procesando en bloques de {options.chunk_size}...",
            current=0,
            total=total_pages,
        ))

        for i in range(0, total_pages, options.chunk_size):
            upper_bound = min(i + options.chunk_size, total_pages)
            label = (
                f"página {i + 1}"
                if options.chunk_size == 1
                else f"páginas {i + 1} a {upper_bound}"
            )

            on_progress(ProgressEvent(
                kind="page_start",
                message=f"Procesando {label}",
                current=i,
                total=total_pages,
            ))

            temp_chunk_path = tmp_dir / f"chunk_{i + 1:04d}_{upper_bound:04d}.pdf"

            try:
                write_chunk_pdf(reader, i, upper_bound, temp_chunk_path)
                markdown_chunk = convert_chunk_with_retries(
                    converter=converter,
                    chunk_path=temp_chunk_path,
                    page_label=label,
                    max_retries=options.max_retries,
                    on_progress=on_progress,
                )

                with open(incremental_output_path, "a", encoding="utf-8") as f:
                    f.write(markdown_chunk)
            finally:
                if temp_chunk_path.exists():
                    temp_chunk_path.unlink()

            on_progress(ProgressEvent(
                kind="page_done",
                message=f"{label[0].upper() + label[1:]} completada",
                current=upper_bound,
                total=total_pages,
            ))

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


def convert_xlsx_to_markdown(source_path: Path, output_path: Path) -> None:
    # Docling pierde columnas sin header y formulas en XLSX. Pandas con
    # data_only=True lee los valores cacheados que Excel guarda al
    # guardar el archivo, y preserva el ancho real de la tabla.
    import pandas as pd

    sheets = pd.read_excel(source_path, sheet_name=None, header=0)

    parts: list[str] = []
    parts.append(f"# {source_path.stem}\n")

    if not sheets:
        parts.append("_(archivo sin hojas legibles)_\n")
    else:
        multi_sheet = len(sheets) > 1
        for sheet_name, df in sheets.items():
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if multi_sheet:
                parts.append(f"## Hoja: {sheet_name}\n")
            if df.empty:
                parts.append("_(hoja vacía)_\n")
                continue
            parts.append(df.to_markdown(index=False))
            parts.append("")

    output_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


def convert_to_markdown(
    source_path: Path,
    output_path: Path,
    on_progress: ProgressCallback | None = None,
    options: ConversionOptions | None = None,
) -> None:
    progress = on_progress or _noop_progress
    opts = options or DEFAULT_OPTIONS
    ext = source_path.suffix.lower()

    if ext == ".pdf":
        convert_pdf_to_markdown(source_path, output_path, opts, progress)
    elif ext in (".xlsx", ".xlsm"):
        progress(ProgressEvent(
            kind="info",
            message=f"Convirtiendo {source_path.name} (pandas)...",
        ))
        convert_xlsx_to_markdown(source_path, output_path)
    else:
        progress(ProgressEvent(
            kind="info",
            message=f"Convirtiendo {source_path.name}...",
        ))
        convert_document_to_markdown(source_path, output_path)

    progress(ProgressEvent(
        kind="done",
        message=f"Conversión completada: {output_path}",
    ))


@dataclass
class BatchEvent:
    kind: str
    message: str
    file: Path | None = None
    output: Path | None = None
    current: int = 0
    total: int = 0
    error: str | None = None


BatchCallback = Callable[[BatchEvent], None]


def _noop_batch(_: BatchEvent) -> None:
    pass


def is_wsl_windows_mount(path: Path) -> bool:
    return str(path.expanduser().resolve()).startswith("/mnt/")


SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".html", ".htm", ".md",
})


def normalize_extensions(exts: list[str] | set[str] | None) -> set[str]:
    if not exts:
        return {".pdf"}
    out: set[str] = set()
    for raw in exts:
        e = raw.strip().lower()
        if not e:
            continue
        if e == "all":
            return set(SUPPORTED_EXTENSIONS)
        if not e.startswith("."):
            e = f".{e}"
        if e not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Extensión no soportada: {e}. "
                f"Soportadas: {sorted(SUPPORTED_EXTENSIONS)}"
            )
        out.add(e)
    return out or {".pdf"}


def discover_files(root: Path, extensions: set[str] | None = None) -> list[Path]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"La ruta no es un directorio: {root}")

    exts = extensions if extensions else {".pdf"}
    matched: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in exts:
            matched.append(p)
    return sorted(matched)


# Alias retrocompatible
def discover_pdfs(root: Path) -> list[Path]:
    return discover_files(root, {".pdf"})


def resolve_batch_output(pdf: Path, output_root: Path) -> Path:
    # Bucket: si el archivo cuelga de "attachments" (export Atlassian),
    # usamos el abuelo (issue/page folder). Sino el padre inmediato.
    # Match case-insensitive para tolerar Attachments / ATTACHMENTS.
    parent = pdf.parent
    bucket = parent.parent.name if parent.name.lower() == "attachments" else parent.name
    if not bucket:
        bucket = "_root"
    # Conservar la extensión original en el output así "X.pdf" y "X.xlsx"
    # no colisionan en "X.md". Resultado: "X.pdf.md", "X.xlsx.md", ...
    return output_root / bucket / f"{pdf.name}.md"


def default_batch_output_root(root: Path) -> Path:
    return root.expanduser().resolve() / "markdowns"


@dataclass(frozen=True)
class PlanItem:
    source: Path
    output: Path
    action: str  # "convert" | "skip_existing" | "skip_duplicate"
    note: str = ""


def _file_sha256(path: Path, chunk_size: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _collision_suffix(source: Path, root: Path) -> str:
    # Path origen relativo al root, sin el filename, joined con "_".
    # Da contexto único: "S-Z_TPMS" vs "EXTRA_TPMS".
    try:
        rel = source.relative_to(root)
    except ValueError:
        rel = source
    parts = list(rel.parts[:-1])
    return "_".join(parts) if parts else "root"


def _rename_with_suffix(output: Path, source: Path, root: Path) -> Path:
    suffix = _collision_suffix(source, root)
    new_name = f"{source.stem}__{suffix}{source.suffix}.md"
    return output.parent / new_name


def plan_batch(
    root: Path,
    output_root: Path,
    extensions: set[str] | None = None,
    *,
    force: bool = False,
) -> list[PlanItem]:
    root = root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    exts = extensions if extensions else {".pdf"}

    files = discover_files(root, exts)

    # 1) Resolver output inicial para cada archivo
    initial: list[tuple[Path, Path]] = [
        (f, resolve_batch_output(f, output_root)) for f in files
    ]

    # 2) Agrupar por output path inicial para detectar colisiones
    groups: dict[Path, list[Path]] = defaultdict(list)
    for src, out in initial:
        groups[out].append(src)

    plan: list[PlanItem] = []

    for out_path, sources in groups.items():
        if len(sources) == 1:
            src = sources[0]
            if out_path.exists() and not force:
                plan.append(PlanItem(src, out_path, "skip_existing", "ya existe"))
            else:
                plan.append(PlanItem(src, out_path, "convert"))
            continue

        # Múltiples archivos compiten por el mismo output → colisión real
        sizes = {s.stat().st_size for s in sources}
        identical = False
        if len(sizes) == 1:
            # Mismo size: confirmar por hash si son los mismos bytes
            hashes = {_file_sha256(s) for s in sources}
            identical = len(hashes) == 1

        if identical:
            # Conservamos el primero (sorted ya en discover_files), saltamos resto.
            kept, others = sources[0], sources[1:]
            if out_path.exists() and not force:
                plan.append(PlanItem(kept, out_path, "skip_existing", "ya existe"))
            else:
                plan.append(PlanItem(kept, out_path, "convert"))
            for other in others:
                try:
                    note = f"duplicado idéntico de {kept.relative_to(root)}"
                except ValueError:
                    note = f"duplicado idéntico de {kept}"
                plan.append(PlanItem(other, out_path, "skip_duplicate", note))
            continue

        # Colisión real con contenido distinto → renombrar todos con sufijo de path
        for src in sources:
            new_out = _rename_with_suffix(out_path, src, root)
            if new_out.exists() and not force:
                plan.append(PlanItem(src, new_out, "skip_existing", "ya existe (renombrado)"))
            else:
                plan.append(PlanItem(
                    src, new_out, "convert",
                    f"renombrado por colisión con otros archivos del mismo bucket",
                ))

    # Orden estable para output determinístico
    plan.sort(key=lambda it: (str(it.output), str(it.source)))
    return plan


def convert_directory(
    root: Path,
    output_root: Path | None = None,
    options: ConversionOptions | None = None,
    on_event: BatchCallback | None = None,
    on_file_progress: Callable[[Path, ProgressEvent], None] | None = None,
    extensions: set[str] | None = None,
    *,
    force: bool = False,
) -> dict:
    emit = on_event or _noop_batch
    opts = options or DEFAULT_OPTIONS

    root = root.expanduser().resolve()
    out_root = (output_root or default_batch_output_root(root)).expanduser().resolve()

    exts = extensions if extensions else {".pdf"}
    plan = plan_batch(root, out_root, exts, force=force)
    total = len(plan)

    exts_label = ", ".join(sorted(exts))
    emit(BatchEvent(
        kind="discovered",
        message=f"Encontrados {total} archivos ({exts_label}) en {root}",
        total=total,
    ))

    out_root.mkdir(parents=True, exist_ok=True)

    converted, skipped, skipped_duplicate, errors = 0, 0, 0, []

    for idx, item in enumerate(plan, start=1):
        try:
            rel_out = item.output.relative_to(out_root)
        except ValueError:
            rel_out = item.output

        if item.action == "skip_existing":
            skipped += 1
            emit(BatchEvent(
                kind="file_skip",
                message=f"[{idx}/{total}] Saltado (ya existe): {rel_out}",
                file=item.source,
                output=item.output,
                current=idx,
                total=total,
            ))
            continue

        if item.action == "skip_duplicate":
            skipped_duplicate += 1
            emit(BatchEvent(
                kind="file_skip_duplicate",
                message=f"[{idx}/{total}] Duplicado: {item.source.name} ({item.note})",
                file=item.source,
                output=item.output,
                current=idx,
                total=total,
            ))
            continue

        item.output.parent.mkdir(parents=True, exist_ok=True)

        emit(BatchEvent(
            kind="file_start",
            message=f"[{idx}/{total}] {item.source.name} → {rel_out}",
            file=item.source,
            output=item.output,
            current=idx,
            total=total,
        ))

        try:
            file_progress = (
                (lambda ev, _src=item.source: on_file_progress(_src, ev))
                if on_file_progress else None
            )
            convert_to_markdown(item.source, item.output, on_progress=file_progress, options=opts)
            converted += 1
            emit(BatchEvent(
                kind="file_done",
                message=f"[{idx}/{total}] {item.source.name} ✓",
                file=item.source,
                output=item.output,
                current=idx,
                total=total,
            ))
        except Exception as e:
            errors.append({"file": str(item.source), "error": str(e)})
            emit(BatchEvent(
                kind="file_error",
                message=f"[{idx}/{total}] {item.source.name} ✗ {e}",
                file=item.source,
                output=item.output,
                current=idx,
                total=total,
                error=str(e),
            ))

    emit(BatchEvent(
        kind="batch_done",
        message=(
            f"Listo: {converted} convertidos, {skipped} saltados, "
            f"{skipped_duplicate} duplicados, {len(errors)} errores"
        ),
        current=total,
        total=total,
    ))

    return {
        "root": str(root),
        "output_root": str(out_root),
        "total": total,
        "converted": converted,
        "skipped": skipped,
        "skipped_duplicate": skipped_duplicate,
        "errors": errors,
    }
