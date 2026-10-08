"""Output naming and path resolution shared by every conversion path.

Kept free of docling imports so tests can import it without loading torch.
"""

from pathlib import Path


def markdown_output_name(source: Path) -> str:
    """Return `<name>.<ext>.md`: the full source file name plus `.md`.

    Keeping the source extension stops `X.pdf` and `X.xlsx` from overwriting
    each other's output.
    """
    return f"{source.name}.md"


def resolve_paths(input_path: Path, output_path: Path | None) -> tuple[Path, Path]:
    source_path = input_path.expanduser().resolve()

    if not source_path.exists():
        raise FileNotFoundError(f"No existe el archivo de entrada: {source_path}")

    if not source_path.is_file():
        raise ValueError(f"La ruta de entrada no es un archivo: {source_path}")

    resolved_output_path = output_path or source_path.with_name(
        markdown_output_name(source_path)
    )
    resolved_output_path = resolved_output_path.expanduser().resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)

    return source_path, resolved_output_path
