#!/usr/bin/env python3
"""
Migrate legacy <stem>.md outputs to the new <stem>.<ext>.md scheme.

Background: before the multi-format batch update, the converter only handled
PDFs and wrote `markdowns/<bucket>/<stem>.md`. After the update, outputs
include the source extension: `<stem>.<ext>.md`. This script renames the old
files so the new skip-if-exists logic finds them.

The script is idempotent: files already in the new scheme are left untouched.

Usage:
    python scripts/migrate_markdowns.py <markdowns-dir> [--source-ext pdf]
                                        [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


KNOWN_SOURCE_SUFFIXES: tuple[str, ...] = (
    ".pdf.md", ".docx.md", ".xlsx.md", ".xlsm.md",
    ".pptx.md", ".html.md", ".htm.md",
)


def needs_migration(path: Path) -> bool:
    name = path.name.lower()
    if not name.endswith(".md"):
        return False
    return not any(name.endswith(suffix) for suffix in KNOWN_SOURCE_SUFFIXES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "markdowns_dir",
        type=Path,
        help="Carpeta raíz con los .md a migrar (ej. ~/dev/.../markdowns).",
    )
    parser.add_argument(
        "--source-ext",
        default="pdf",
        help="Extensión del archivo fuente original (default: pdf). "
        "Se agrega como <stem>.<source-ext>.md.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No renombra; solo lista lo que haría.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.markdowns_dir.expanduser().resolve()
    source_ext = args.source_ext.lower().lstrip(".")

    if not root.is_dir():
        print(f"Error: no es un directorio: {root}", file=sys.stderr)
        return 1

    candidates = [p for p in root.rglob("*.md") if needs_migration(p)]
    if not candidates:
        print(f"Nada para migrar. Todos los .md en {root} ya están en formato nuevo.")
        return 0

    print(f"Encontrados {len(candidates)} archivos para migrar a <stem>.{source_ext}.md")
    if args.dry_run:
        print("Modo dry-run, no se renombra nada:")

    renamed = 0
    skipped = 0
    for src in candidates:
        new_name = f"{src.stem}.{source_ext}.md"
        target = src.with_name(new_name)
        if target.exists():
            print(f"  ⚠ {src.relative_to(root)}  →  {target.name}  (destino ya existe, saltado)")
            skipped += 1
            continue
        print(f"  • {src.relative_to(root)}  →  {target.name}")
        if not args.dry_run:
            src.rename(target)
        renamed += 1

    print()
    if args.dry_run:
        print(f"Dry-run: {renamed} archivos serían renombrados, {skipped} conflictos.")
    else:
        print(f"Listo: {renamed} renombrados, {skipped} saltados por conflicto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
