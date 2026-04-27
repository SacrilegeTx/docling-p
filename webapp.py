import asyncio
import json
import queue
import shutil
import tempfile
import threading
import uuid
import webbrowser
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask

from core import (
    DEFAULT_OPTIONS,
    ConversionOptions,
    ProgressEvent,
    convert_to_markdown,
    ensure_environment,
)


SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".pptx", ".html", ".htm", ".md"}
STATIC_DIR = Path(__file__).parent / "static"
VALID_OPTION_KEYS = {"chunk_size", "max_retries", "do_ocr", "table_mode", "num_threads"}


@dataclass
class Job:
    id: str
    filename: str
    staging_dir: Path
    input_path: Path
    output_path: Path
    options: ConversionOptions = field(default_factory=lambda: DEFAULT_OPTIONS)
    queue: "queue.Queue[ProgressEvent | None]" = field(default_factory=queue.Queue)
    status: str = "queued"
    position: int = 0
    error: str | None = None


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()
job_queue: "queue.Queue[str | None]" = queue.Queue()


def _parse_options(raw: str) -> ConversionOptions:
    if not raw or raw.strip() in ("", "{}"):
        return DEFAULT_OPTIONS
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"options no es JSON válido: {e}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="options debe ser un objeto JSON")
    unknown = set(data) - VALID_OPTION_KEYS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Opciones desconocidas: {sorted(unknown)}. Permitidas: {sorted(VALID_OPTION_KEYS)}",
        )
    try:
        return ConversionOptions(**data)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Opciones inválidas: {e}")


def _worker_loop() -> None:
    while True:
        job_id = job_queue.get()
        if job_id is None:
            return
        job = jobs.get(job_id)
        if job is None:
            continue

        with jobs_lock:
            for other in jobs.values():
                if other.status == "queued" and other.id != job_id:
                    other.position = max(0, other.position - 1)
                    if other.position > 0:
                        other.queue.put(ProgressEvent(
                            kind="queued",
                            message=f"En cola, posición {other.position}",
                            current=other.position,
                        ))
            job.status = "running"
            job.position = 0

        try:
            convert_to_markdown(
                job.input_path,
                job.output_path,
                on_progress=lambda e, _q=job.queue: _q.put(e),
                options=job.options,
            )
            job.status = "done"
        except Exception as e:
            job.status = "error"
            job.error = str(e)
            job.queue.put(ProgressEvent(kind="error", message=str(e)))
        finally:
            job.queue.put(None)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_environment()
    worker = threading.Thread(target=_worker_loop, daemon=True)
    worker.start()
    yield
    job_queue.put(None)


app = FastAPI(lifespan=lifespan, title="Docling Markdown Converter")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/convert")
async def convert(
    file: UploadFile,
    options: str = Form("{}"),
) -> dict[str, str | int]:
    filename = file.filename or "input"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Extensión no soportada: {ext or '(ninguna)'}. Soportadas: {sorted(SUPPORTED_EXTS)}",
        )

    conversion_opts = _parse_options(options)

    job_id = uuid.uuid4().hex
    staging_dir = Path(tempfile.mkdtemp(prefix=f"docling-{job_id}-"))
    input_path = staging_dir / filename
    output_path = staging_dir / (Path(filename).stem + ".md")

    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    with jobs_lock:
        ahead = sum(1 for j in jobs.values() if j.status in ("queued", "running"))
        job = Job(
            id=job_id,
            filename=filename,
            staging_dir=staging_dir,
            input_path=input_path,
            output_path=output_path,
            options=conversion_opts,
            position=ahead,
        )
        jobs[job_id] = job

    if ahead > 0:
        job.queue.put(ProgressEvent(
            kind="queued",
            message=f"En cola, posición {ahead}",
            current=ahead,
        ))

    job_queue.put(job_id)
    return {"job_id": job_id, "filename": filename, "position": ahead}


@app.get("/progress/{job_id}")
async def progress(job_id: str) -> EventSourceResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    async def stream():
        while True:
            event = await asyncio.to_thread(job.queue.get)
            if event is None:
                return
            payload = {
                "kind": event.kind,
                "message": event.message,
                "current": event.current,
                "total": event.total,
            }
            yield {"event": event.kind, "data": json.dumps(payload)}
            if event.kind == "error":
                return

    return EventSourceResponse(stream())


@app.get("/download/{job_id}")
async def download(job_id: str) -> FileResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if job.status != "done":
        raise HTTPException(
            status_code=409,
            detail=f"Job en estado {job.status}, no se puede descargar",
        )
    if not job.output_path.exists():
        raise HTTPException(status_code=404, detail="Archivo de salida no encontrado")

    def cleanup() -> None:
        shutil.rmtree(job.staging_dir, ignore_errors=True)
        with jobs_lock:
            jobs.pop(job_id, None)

    return FileResponse(
        job.output_path,
        media_type="text/markdown",
        filename=Path(job.filename).stem + ".md",
        background=BackgroundTask(cleanup),
    )


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _open_browser_when_ready(url: str) -> None:
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()


if __name__ == "__main__":
    import uvicorn

    HOST, PORT = "127.0.0.1", 8000
    _open_browser_when_ready(f"http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
