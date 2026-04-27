# Docling Markdown converter

This project converts PDF and office documents to Markdown using
[Docling](https://github.com/docling-project/docling). It ships with two ways
to run conversions:

- A **command-line interface** for scripting and power users.
- A **local web UI** with drag-and-drop, live progress, and an advanced-options
  panel for less technical users.

Both interfaces share the same conversion core, so behavior and tuning options
match across the two.

## What it does

The shared core converts documents supported by Docling into Markdown using
two paths:

- **PDF files** use a safer page-by-page flow. The PDF is split into temporary
  chunks (one page each by default), each chunk is converted, failed chunks
  are retried, progress is written incrementally, and the final Markdown is
  copied to the output path.
- **Non-PDF files** use Docling's direct conversion flow — the right path for
  formats such as Word, Excel, PowerPoint, and HTML files because they don't
  use the same page-based structure as PDFs.

The default PDF configuration keeps OCR disabled and runs table extraction in
`FAST` mode. That choice prioritizes stability for born-digital PDFs with
extensive tables. Both behaviors are configurable per-conversion (see
[Conversion options](#conversion-options)).

After Docling produces Markdown, a post-processing pipeline restructures
flattened "row + description + XML" tables and pretty-prints fenced XML
blocks. See [Post-processing pipeline](#post-processing-pipeline).

## Supported input files

- `.pdf`
- `.docx`
- `.xlsx`
- `.pptx`
- `.html`, `.htm`
- `.md`
- other formats supported by the installed Docling version

PDF files receive special handling because large tables can make full-document
conversion expensive. Other formats are sent directly to Docling.

## Requirements

- Python compatible with the version declared in `pyproject.toml`.
- [`uv`](https://docs.astral.sh/uv/) for dependency management.
- A Hugging Face token stored in `.env` as `HF_TOKEN`.
- Windows, Linux, or WSL.

Project dependencies (declared in `pyproject.toml`):

- `docling` — document conversion engine
- `pypdf[crypto]` — PDF chunking; the `crypto` extra adds `cryptography` so
  encrypted PDFs (AES) can be opened
- `lxml` — XML pretty-printing in the post-processing pipeline
- `python-dotenv` — loads `HF_TOKEN` from `.env`
- `fastapi`, `uvicorn[standard]`, `python-multipart`, `sse-starlette` — power
  the local web UI

## Installation

Clone the repository and install dependencies with `uv`:

```powershell
git clone <your-repository-url>
cd docling-p
uv venv --python (python -c "import sys; print(sys.executable)") .venv
uv sync
```

The `uv venv` command creates a local `.venv` folder before dependencies are
installed. The command above asks Python for the path of the active interpreter
and tells `uv` to create the virtual environment from that Python installation.

If you prefer to pass the Python version directly in PowerShell:

```powershell
uv venv --python 3.14 .venv
uv sync
```

### Clean installation in Ubuntu or WSL

If you use Ubuntu or WSL, the cleanest setup is to keep the project inside the
Linux filesystem instead of working directly from `/mnt/c`. Python virtual
environments are more reliable when they live in the same filesystem as the
Python interpreter.

```bash
mkdir -p ~/projects
cd ~/projects
git clone <your-repository-url> docling-p
cd docling-p
uv venv --python "$(python3 -c 'import sys; print(sys.executable)')" .venv
uv sync
```

You can still convert files stored in Windows by passing their `/mnt/c/...`
path:

```bash
uv run python main.py "/mnt/c/Users/your-user/Downloads/Documents/input.pdf"
```

### Installing while the project stays in `/mnt/c`

Keeping the project in `/mnt/c` works, but installation is slower because WSL
writes a Linux virtual environment into a Windows-mounted filesystem. Use
`UV_LINK_MODE=copy` so `uv` copies files instead of trying to hardlink them
across filesystems:

```bash
uv venv --python "$(python3 -c 'import sys; print(sys.executable)')" .venv
UV_LINK_MODE=copy uv sync
```

The `Failed to hardlink files; falling back to full copy` warning is not fatal
— installation still finishes successfully.

## Environment setup

The project loads environment variables from `.env` using `python-dotenv`.
Create your local `.env` file from the example:

```powershell
copy .env.example .env
```

Then edit `.env` and set your Hugging Face token:

```env
HF_TOKEN=your_huggingface_token_here
```

Do not commit your real `.env`. Keep secrets local.

## Quick start (web UI)

The fastest path for non-technical users:

- **Windows**: double-click `start.bat`.
- **Linux / macOS / WSL**: run `./start.sh` from a terminal.

The launcher starts a local server on `http://localhost:8000` and opens your
default browser. Drag a document onto the drop zone, watch the progress, and
the converted `.md` downloads automatically when conversion finishes.

The server is local-only (`127.0.0.1`) — no files leave your machine.

To stop the server, close the launcher window or press `Ctrl+C` in the
terminal.

## Web UI usage

The web UI provides:

- **Drag-and-drop upload** with a click-to-browse fallback.
- **Live page counter** (`X / Y pages`) showing the current page being
  processed alongside the progress bar.
- **Streaming progress log** with each event the converter emits (chunk start,
  retries, warnings).
- **FIFO queue**: if you start a second conversion while another is running,
  it waits its turn. The UI shows an "Esperando en cola, posición N" banner
  until the worker picks it up.
- **Automatic download** of the resulting `.md` when conversion finishes —
  files are not persisted on the server.
- **Advanced options panel** (collapsed by default) to tune the same
  parameters available on the CLI.

### Concurrency

The server processes one conversion at a time on purpose. Docling loads ML
models that consume significant RAM, so running two conversions in parallel
risks out-of-memory failures. Additional uploads are queued and reported back
to the user with their position.

### Running on a different port

Edit `webapp.py` and change the `HOST` / `PORT` constants near the bottom of
the file. The browser auto-launch and CORS-free local-only behavior assume
`127.0.0.1`.

## CLI usage

Run the script with the document you want to convert:

```powershell
uv run python main.py "C:\Users\your-user\Downloads\Documents\input.pdf"
```

When `--output` is not passed, the script creates a Markdown file next to the
input document with the same base name. So:

```text
C:\Users\your-user\Downloads\Documents\input.pdf
```

becomes:

```text
C:\Users\your-user\Downloads\Documents\input.md
```

### Save to a custom output path

```powershell
uv run python main.py "C:\path\to\input.pdf" --output "C:\path\to\out\input.md"
```

The short flag `-o` works the same way. The script creates the output folder
when it does not exist.

### CLI parameters

| Parameter         | Default | Description |
| ----------------- | ------- | ----------- |
| `input`           | —       | Path to the document to convert (required). Quote it when it contains spaces. |
| `--output`, `-o`  | input path with `.md` extension | Path to the Markdown file to create. |
| `--chunk-size`    | `1`     | Pages per chunk when processing PDFs. Higher = less overhead, more RAM. |
| `--max-retries`   | `2`     | Retries per chunk on transient errors. |
| `--ocr`           | off     | Enable OCR. Costly; only useful for scanned PDFs without embedded text. |
| `--table-mode`    | `fast`  | Table detection mode (`fast` or `accurate`). |
| `--threads`       | `1`     | Threads for the CPU accelerator. |

View command help anytime:

```powershell
uv run python main.py --help
```

### CLI examples

Convert a scanned PDF with OCR and accurate tables:

```bash
uv run python main.py "scanned.pdf" --ocr --table-mode accurate
```

Speed up a small, well-behaved PDF:

```bash
uv run python main.py "small.pdf" --chunk-size 5 --threads 4
```

## Conversion options

The same options are exposed in both the CLI (flags) and the web UI (advanced
options panel):

- `chunk_size` (default `1`): pages per chunk for the PDF flow. Higher values
  reduce per-chunk overhead but require more RAM and increase the cost of a
  single failure (the whole chunk needs retrying).
- `max_retries` (default `2`): how many times a failed chunk is retried
  before the conversion aborts.
- `do_ocr` (default off): enable OCR for scanned PDFs. Disabled by default
  because RapidOCR uses substantial memory and adds no value when the PDF
  already contains embedded text.
- `table_mode` (default `fast`): TableFormer mode. `fast` is the
  stability-first choice for large born-digital PDFs with many tables.
  `accurate` reconstructs complex tables better at the cost of speed and
  memory.
- `num_threads` (default `1`): threads for the CPU accelerator. Higher means
  faster conversion but higher peak memory.

### When to change these defaults

The defaults are best for born-digital PDFs with large tables. Change them
only when you understand the trade-offs:

- Increase `chunk_size` when your PDFs are small, reliable, and you want
  faster conversion.
- Keep `chunk_size = 1` when PDFs are large, table-heavy, or prone to memory
  errors.
- Switch `table_mode` to `accurate` only when table quality matters more than
  runtime and memory.
- Enable `do_ocr` only for scanned PDFs where text is not embedded in the
  document.

If the document is already text-based, OCR and heavier table analysis can add
cost without improving the Markdown enough to justify the risk.

## How it works

The conversion starts by loading `.env`, validating `HF_TOKEN`, and resolving
the input and output paths. Then the input is checked for existence.

For PDF files:

1. Create a temporary `tmp` folder.
2. Open the PDF with `pypdf`.
3. Split the document into `chunk_size`-page chunks.
4. Convert each chunk with Docling, applying the configured options.
5. Retry each chunk up to `max_retries` times when conversion fails.
6. Run the post-processing pipeline on each converted chunk's Markdown.
7. Append each converted chunk to a temporary `.partial.md` file.
8. Copy the completed partial file to the final output path.
9. Remove the temporary folder.

For non-PDF files:

1. Send the document directly to `DocumentConverter`.
2. Export the converted document to Markdown.
3. Run the post-processing pipeline.
4. Write the Markdown to the output path.

This split keeps the PDF workflow resilient while keeping other document
types simple.

## Post-processing pipeline

After Docling exports Markdown, two transformations run before the file is
written. Both are idempotent and conservative — a block that does not match
the expected pattern passes through unchanged.

### Phase 1: Restructure flattened "row + description + XML" tables

Some documents contain tables shaped as `row number | description | XML
example` where each cell is wide (often because the XML cell holds many
lines). When the layout detector cannot identify the region as a table,
Docling emits the rows as a single fenced code block with everything
concatenated into one line.

The pipeline detects that pattern and re-segments each block into individual
rows. For every detected row (or row group, when the original table used
rowspan) it emits:

- A `### Fila N` (or `### Filas N1, N2, ...`) heading.
- The row description as plain text.
- A separate ` ```xml ` fenced block with that row's XML example.

This preserves the row-to-XML mapping and keeps each example searchable with
tools like `rg`.

### Phase 2: Pretty-print fenced XML blocks

Every fenced code block whose content looks like XML (starts with `<` and
contains `</` or `/>`) is reformatted with one tag per line and consistent
indentation. The pretty-printer uses `lxml` with a recovering parser so it
tolerates fragments without a single root element, OCR artifacts, and
unescaped characters that would break a strict XML parser. If `lxml` cannot
recover anything from the block, the script falls back to a regex-based
pretty-printer that does not validate the structure.

### When the pipeline does nothing

Both transformations only act on fenced code blocks that match their
detection heuristics. Plain Markdown tables, prose, and code blocks for
non-XML content are left untouched.

## Windows notes

Use quotes around Windows paths because document names often contain spaces:

```powershell
uv run python main.py "C:\Users\your-user\Downloads\Documents\my-file.pdf"
```

If you run the project through WSL against a Windows-mounted folder, be
careful with virtual environments created by Windows tools. A Windows
`.venv\Scripts` folder behaves differently from a Linux `.venv/bin` folder.
When in doubt, use the same environment where you installed the dependencies.

## Troubleshooting

### `Falta la variable de entorno requerida: HF_TOKEN`

Create `.env` and set `HF_TOKEN`:

```env
HF_TOKEN=your_huggingface_token_here
```

### `cryptography>=3.1 is required for AES algorithm`

Your PDF is encrypted. The `pypdf[crypto]` extra in `pyproject.toml` brings
in the required `cryptography` package. If you upgraded from an older version
of this project, run `uv sync` to install the missing dependency.

### `No existe el archivo de entrada`

Check the path and wrap it in quotes when it contains spaces.

### The conversion uses too much memory

Keep OCR disabled for born-digital PDFs (the default). For scanned PDFs OCR
is required, but it can increase memory usage significantly. Reducing
`chunk_size` to `1` and `num_threads` to `1` also lowers peak memory.

### Tables don't look perfect in Markdown

Markdown has limited table layout support. Tables with very wide cells,
nested headers, or merged cells may still need manual cleanup. The
post-processing pipeline already handles the worst case — tables that
Docling collapsed into a single-line code block with embedded XML examples.
You can also try `--table-mode accurate` for better detection at the cost of
speed.

### Browser does not open automatically

The web UI tries to open your default browser when launching. If it fails
(common in headless environments or WSL without `wslview`), open
[http://localhost:8000](http://localhost:8000) manually.

### `uv run` fails in WSL with a Windows `.venv`

Use the same platform that created the environment, or recreate the virtual
environment from the platform you are using. To switch the project to WSL,
close any Windows Python processes that are using the old `.venv`, delete
the virtual environment, and recreate it from WSL:

```bash
rm -rf .venv
uv venv --python "$(python3 -c 'import sys; print(sys.executable)')" .venv
UV_LINK_MODE=copy uv sync
```

## Limitations

This project focuses on reliable Markdown extraction, not pixel-perfect
document reconstruction:

- Complex PDF layouts may still require manual Markdown cleanup, even after
  the post-processing pipeline.
- Scanned PDFs need `--ocr` (CLI) or the OCR toggle (web UI) enabled.
- Non-PDF files are converted directly and don't have chunk-level retry
  logic.
- Very large documents can still take time to process.
- The web UI processes one job at a time on purpose — see
  [Concurrency](#concurrency).

## Project structure

```text
.
├── core.py            # Pure conversion logic + ConversionOptions + ProgressEvent
├── main.py            # CLI wrapper
├── webapp.py          # FastAPI web UI backend (upload, SSE progress, download)
├── static/
│   ├── index.html     # Web UI markup
│   └── app.js         # Drag-and-drop, SSE handling, options form
├── start.bat          # Windows double-click launcher
├── start.sh           # Unix shell launcher
├── pyproject.toml     # Project metadata and dependencies
├── uv.lock            # Locked dependency versions
├── .env.example       # Example environment file
└── README.md          # Project documentation
```

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE) for
details.
