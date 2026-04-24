# Docling Markdown converter

This project provides a small Python command-line script that converts PDF and
office documents to Markdown by using [Docling](https://github.com/docling-project/docling).
It is designed for local document conversion, with extra care for large PDFs
that contain long tables.

The script accepts an input document path, converts it to Markdown, and writes a
`.md` file either next to the original document or in a custom path passed with
`--output`.

## What it does

`main.py` converts documents supported by Docling into Markdown. The script has
two conversion paths:

- **PDF files** use a safer page-by-page flow. The script splits the PDF into
  temporary one-page chunks, converts each chunk, retries failed chunks, writes
  progress incrementally, and then copies the final Markdown file to the output
  path.
- **Non-PDF files** use Docling's direct conversion flow. This is the right
  path for formats such as Word, Excel, PowerPoint, and HTML files because they
  don't use the same page-based structure as PDFs.

The PDF path keeps OCR disabled and table extraction enabled in `FAST` mode.
That configuration was chosen for born-digital PDFs where text and tables are
already embedded in the document. It reduces memory pressure and avoids the OCR
pipeline when OCR doesn't add value.

## Supported input files

Docling supports several document formats. In practical terms, this script is
intended for files such as:

- `.pdf`
- `.docx`
- `.xlsx`
- `.pptx`
- `.html`
- other formats supported by the installed Docling version

PDF files receive special handling because large tables can make full-document
conversion expensive. Other formats are sent directly to Docling.

## Requirements

You need the following tools and configuration:

- Python compatible with the version declared in `pyproject.toml`.
- [`uv`](https://docs.astral.sh/uv/) for dependency management.
- A Hugging Face token stored in `.env` as `HF_TOKEN`.
- Windows, Linux, or WSL. This project was originally used from Windows paths,
  so the examples include Windows-friendly commands.

The project dependencies are declared in `pyproject.toml`:

- `docling`
- `pypdf`
- `python-dotenv`

## Installation

Clone the repository and install the dependencies with `uv`:

```powershell
git clone <your-repository-url>
cd docling-p
uv venv --python (python -c "import sys; print(sys.executable)") .venv
uv sync
```

The `uv venv` command creates a local `.venv` folder before dependencies are
installed. The command above asks Python for the path of the currently active
interpreter and tells `uv` to create the virtual environment from that Python
installation.

If you prefer to pass the Python version directly in PowerShell, you can use a
version selector instead:

```powershell
uv venv --python 3.14 .venv
uv sync
```

Using the interpreter path is more explicit and avoids depending on the exact
text returned by `python --version`.

### Clean installation in Ubuntu or WSL

If you use Ubuntu or WSL, the cleanest setup is to keep the project inside the
Linux filesystem instead of working directly from `/mnt/c`. Python virtual
environments contain many small files and executable links, and they are more
reliable when they live in the same filesystem as the Python interpreter.

Recommended layout:

```bash
mkdir -p ~/projects
cp -a /mnt/c/Data/Projects/Python/docling-p ~/projects/docling-p
cd ~/projects/docling-p
rm -rf .venv
uv venv --python "$(python3 -c 'import sys; print(sys.executable)')" .venv
uv sync
```

If you prefer to clone the repository directly into WSL, use:

```bash
mkdir -p ~/projects
cd ~/projects
git clone <your-repository-url> docling-p
cd docling-p
uv venv --python "$(python3 -c 'import sys; print(sys.executable)')" .venv
uv sync
```

You can still convert files stored in Windows by passing their `/mnt/c/...`
path to the script:

```bash
uv run python main.py "/mnt/c/Users/your-user/Downloads/Documents/input.pdf"
```

### Installing while the project stays in `/mnt/c`

Keeping the project in `/mnt/c` also works, but dependency installation can be
slower because WSL is writing a Linux virtual environment into a Windows-mounted
filesystem. In that case, use `UV_LINK_MODE=copy` to tell `uv` to copy files
instead of trying to create hardlinks across filesystems:

```bash
uv venv --python "$(python3 -c 'import sys; print(sys.executable)')" .venv
UV_LINK_MODE=copy uv sync
```

This setting avoids warnings like:

```text
Failed to hardlink files; falling back to full copy.
```

That warning is not fatal. It means `uv` couldn't hardlink files from its cache
to the target environment and copied them instead. The installation can still
finish successfully.

If you are already inside the project folder and `.venv` doesn't exist yet,
create it before syncing dependencies:

```powershell
uv venv --python (python -c "import sys; print(sys.executable)") .venv
uv sync
```

If `.venv` already exists and was created by the same operating system you are
using now, running only `uv sync` is enough.

## Environment setup

The script loads environment variables from `.env` by using `python-dotenv`.
Create your local `.env` file from the example file:

```powershell
copy .env.example .env
```

Then edit `.env` and set your Hugging Face token:

```env
HF_TOKEN=your_huggingface_token_here
```

Do not commit your real `.env` file. Keep secrets local.

## Usage

Run the script with the document you want to convert.

### Save next to the input file

When you don't pass `--output`, the script creates a Markdown file next to the
input document with the same base name.

```powershell
uv run python main.py "C:\Users\your-user\Downloads\Documents\pdf-to-convert.pdf"
```

If the input file is:

```text
C:\Users\your-user\Downloads\Documents\pdf-to-convert.pdf
```

The output file becomes:

```text
C:\Users\your-user\Downloads\Documents\pdf-to-convert.md
```

### Save to a custom output path

Use `--output` or `-o` to choose where to save the Markdown file.

```powershell
uv run python main.py "C:\Users\your-user\Downloads\Documents\input.pdf" --output "C:\Users\your-user\Downloads\Markdown\input.md"
```

The short flag works the same way:

```powershell
uv run python main.py "C:\Users\your-user\Downloads\Documents\input.docx" -o "C:\Users\your-user\Downloads\Markdown\input.md"
```

The script creates the output folder when it doesn't exist.

## Parameters

The script exposes a small command-line interface.

| Parameter | Required | Description |
| --- | --- | --- |
| `input` | Yes | Path to the document to convert. Use quotes when the path contains spaces. |
| `--output`, `-o` | No | Path to the Markdown file to create. Defaults to the input path with `.md` extension. |

You can also view the command help:

```powershell
uv run python main.py --help
```

## How the script works

The conversion starts by loading `.env`, validating `HF_TOKEN`, and resolving
the input and output paths. It then checks that the input exists and is a file.

For PDF files, the script uses this flow:

1. Create a temporary `tmp` folder.
2. Open the PDF with `pypdf`.
3. Split the document into one-page chunks.
4. Convert each chunk with Docling.
5. Retry each chunk up to two times when conversion fails.
6. Append each converted chunk to a temporary `.partial.md` file.
7. Copy the completed partial file to the final output path.
8. Remove the temporary folder.

For non-PDF files, the script uses this flow:

1. Send the document directly to `DocumentConverter`.
2. Export the converted document to Markdown.
3. Write the Markdown to the output path.

This split keeps the PDF workflow resilient while keeping other document types
simple.

## PDF conversion settings

The PDF converter is intentionally conservative:

- OCR is disabled with `do_ocr = False`.
- Table structure extraction is enabled with `do_table_structure = True`.
- TableFormer runs in `TableFormerMode.FAST` mode.
- Conversion uses CPU with one thread.
- PDF chunks use one page per chunk.
- Failed chunks are retried two times.

These defaults prioritize stability for large born-digital PDFs with extensive
tables. If you need to process scanned PDFs, you may need to enable OCR and
accept the higher memory cost.

### Why `TableFormerMode.FAST` is used

Docling can analyze table structure with different TableFormer modes. This
script uses `TableFormerMode.FAST` because the original target document had
large, complex tables but also contained real embedded text. In that scenario,
the goal is to preserve table structure without spending extra time and memory
on the most expensive table analysis path.

`FAST` is a stability-first choice:

- It reduces processing cost compared with heavier table-structure modes.
- It is usually enough for born-digital PDFs where text and table boundaries are
  already reasonably extractable.
- It lowers the chance of memory pressure when a PDF contains many long tables.

The trade-off is that complex tables may not be reconstructed perfectly. Nested
headers, merged cells, multi-page tables, and visually dense layouts can still
need manual cleanup in the generated Markdown.

### Why `CHUNK_SIZE = 1` is used

The script converts PDFs one page at a time. That setting is intentionally slow
but safer for large PDFs.

Using one-page chunks gives the script a smaller working set:

- Each Docling conversion handles only one page.
- A failed page can be retried without restarting the entire document.
- Successfully converted pages are appended to a partial Markdown file as the
  script progresses.
- Temporary chunk PDFs are deleted immediately after each page finishes.

This matters because the original PDF had extensive tables and previously hit a
`std::bad_alloc` memory failure during preprocessing when OCR was involved.
Keeping `CHUNK_SIZE = 1`, disabling OCR, using `TableFormerMode.FAST`, and
limiting the converter to one CPU thread all push the script toward predictable
memory usage.

The trade-off is speed. A higher chunk size may be faster, but it increases the
amount of document content Docling must hold and analyze at once. If you raise
`CHUNK_SIZE`, test with representative PDFs before using it for long documents.

### When to change these settings

The defaults are best for born-digital PDFs with large tables. Change them only
when you understand the trade-off:

- Increase `CHUNK_SIZE` when your PDFs are small, reliable, and you want faster
  conversion.
- Keep `CHUNK_SIZE = 1` when PDFs are large, table-heavy, or prone to memory
  errors.
- Keep `TableFormerMode.FAST` when you prefer speed and stability.
- Try a more accurate table mode only when table quality matters more than
  runtime and memory use.
- Enable OCR only for scanned PDFs where text is not embedded in the document.

In other words: don't tune these values blindly. If the document is already
text-based, OCR and heavier table analysis can add cost without improving the
Markdown enough to justify the risk.

## Windows notes

Use quotes around Windows paths because document names often contain spaces:

```powershell
uv run python main.py "C:\Users\your-user\Downloads\Documents\my-file.pdf"
```

If you run the project through WSL against a Windows-mounted folder, be careful
with virtual environments created by Windows tools. A Windows `.venv\Scripts`
folder can behave differently from a Linux `.venv/bin` folder. When in doubt,
use the same environment where you installed the dependencies.

## Troubleshooting

Use these checks when something fails.

### `Falta la variable de entorno requerida: HF_TOKEN`

Create `.env` and set `HF_TOKEN`:

```env
HF_TOKEN=your_huggingface_token_here
```

### `No existe el archivo de entrada`

Check the path and wrap it in quotes when it contains spaces:

```powershell
uv run python main.py "C:\full\path\to\document.pdf"
```

### The conversion uses too much memory

For born-digital PDFs, keep OCR disabled. The current script already does this.
For scanned PDFs, OCR may be required, but it can increase memory usage
significantly.

### Tables don't look perfect in Markdown

Markdown has limited table layout support. Complex tables from PDFs or
spreadsheets may need manual cleanup after conversion.

### `uv run` fails in WSL with a Windows `.venv`

Use the same platform that created the environment, or recreate the virtual
environment from the platform you are using. For example, if the project was set
up in Windows PowerShell, run it from Windows PowerShell.

If you want to switch the project to WSL, close any Windows Python processes
that are using the old `.venv`, delete the virtual environment, and recreate it
from WSL:

```bash
rm -rf .venv
uv venv --python "$(python3 -c 'import sys; print(sys.executable)')" .venv
UV_LINK_MODE=copy uv sync
```

If Windows blocks `.venv\Scripts\python.exe`, a Python process is still running
from the old Windows virtual environment. Stop that process first, then delete
`.venv` again.

## Limitations

The script focuses on reliable Markdown extraction, not pixel-perfect document
reconstruction. Keep these limitations in mind:

- Complex PDF layouts may require manual Markdown cleanup.
- Scanned PDFs are not handled by the default PDF settings because OCR is
  disabled.
- Non-PDF files are converted directly and don't have chunk-level retry logic.
- Very large documents can still take time to process.

## Possible improvements

Future versions could add:

- A `--ocr` flag for scanned PDFs.
- A `--chunk-size` option for advanced PDF tuning.
- A `--retries` option for adjusting retry behavior.
- A `--keep-temp` flag for debugging failed chunks.
- Format-specific options for spreadsheets and presentations.

## Project structure

The repository is intentionally small:

```text
.
├── main.py          # Command-line converter
├── pyproject.toml   # Project metadata and dependencies
├── uv.lock          # Locked dependency versions
├── .env.example     # Example environment file
└── README.md        # Project documentation
```

## License

Add a license before publishing the repository publicly. If you want others to
reuse the script, choose a permissive license such as MIT or Apache 2.0.
