from pathlib import Path


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
