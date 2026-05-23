import asyncio
import json
import platform
import queue
import re
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
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask

from core import (
    DEFAULT_OPTIONS,
    SUPPORTED_EXTENSIONS,
    ConversionOptions,
    ProgressEvent,
    convert_to_markdown,
    default_batch_output_root,
    ensure_environment,
    is_wsl_windows_mount,
    normalize_extensions,
    plan_batch,
)


SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".pptx", ".html", ".htm", ".md"}
STATIC_DIR = Path(__file__).parent / "static"
VALID_OPTION_KEYS = {"chunk_size", "max_retries", "do_ocr", "table_mode", "num_threads"}


@dataclass
class Job:
    id: str
    filename: str
    input_path: Path
    output_path: Path
    staging_dir: Path | None = None
    batch_id: str | None = None
    options: ConversionOptions = field(default_factory=lambda: DEFAULT_OPTIONS)
    queue: "queue.Queue[ProgressEvent | None]" = field(default_factory=queue.Queue)
    status: str = "queued"
    position: int = 0
    error: str | None = None


@dataclass
class BatchSession:
    id: str
    root: Path
    output_root: Path
    options: ConversionOptions
    force: bool
    total: int
    job_ids: list[str]
    files: list[dict] = field(default_factory=list)
    skipped: int = 0
    converted: int = 0
    failed: int = 0
    queue: "queue.Queue[dict | None]" = field(default_factory=queue.Queue)
    finished: bool = False


jobs: dict[str, Job] = {}
batches: dict[str, BatchSession] = {}
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


def _emit_batch(batch: BatchSession, payload: dict) -> None:
    batch.queue.put(payload)


def _update_file_status(batch: BatchSession, job_id: str, status: str, error: str | None = None) -> None:
    for entry in batch.files:
        if entry.get("job_id") == job_id:
            entry["status"] = status
            if error is not None:
                entry["error"] = error
            return


def _finalize_batch_if_done(batch: BatchSession) -> None:
    done = batch.converted + batch.failed + batch.skipped
    if done >= batch.total and not batch.finished:
        batch.finished = True
        _emit_batch(batch, {
            "kind": "batch_done",
            "message": (
                f"Listo: {batch.converted} convertidos, "
                f"{batch.skipped} saltados, {batch.failed} errores"
            ),
            "total": batch.total,
            "converted": batch.converted,
            "skipped": batch.skipped,
            "failed": batch.failed,
        })
        batch.queue.put(None)


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
                if (
                    other.status == "queued"
                    and other.id != job_id
                    and other.batch_id is None
                ):
                    other.position = max(0, other.position - 1)
                    if other.position > 0:
                        other.queue.put(ProgressEvent(
                            kind="queued",
                            message=f"En cola, posición {other.position}",
                            current=other.position,
                        ))
            job.status = "running"
            job.position = 0

        batch = batches.get(job.batch_id) if job.batch_id else None

        if batch is not None:
            _update_file_status(batch, job.id, "running")
            _emit_batch(batch, {
                "kind": "file_start",
                "job_id": job.id,
                "filename": job.filename,
                "source": str(job.input_path),
                "output": str(job.output_path),
                "message": f"Procesando {job.filename}",
            })

        try:
            if batch is not None:
                def _proxy(ev: ProgressEvent, _b=batch, _j=job) -> None:
                    _emit_batch(_b, {
                        "kind": "file_progress",
                        "job_id": _j.id,
                        "filename": _j.filename,
                        "inner_kind": ev.kind,
                        "message": ev.message,
                        "current": ev.current,
                        "total": ev.total,
                    })

                convert_to_markdown(
                    job.input_path,
                    job.output_path,
                    on_progress=_proxy,
                    options=job.options,
                )
            else:
                convert_to_markdown(
                    job.input_path,
                    job.output_path,
                    on_progress=lambda e, _q=job.queue: _q.put(e),
                    options=job.options,
                )
            job.status = "done"

            if batch is not None:
                batch.converted += 1
                _update_file_status(batch, job.id, "done")
                _emit_batch(batch, {
                    "kind": "file_done",
                    "job_id": job.id,
                    "filename": job.filename,
                    "output": str(job.output_path),
                    "converted": batch.converted,
                    "skipped": batch.skipped,
                    "failed": batch.failed,
                    "total": batch.total,
                })
        except Exception as e:
            job.status = "error"
            job.error = str(e)

            if batch is not None:
                batch.failed += 1
                _update_file_status(batch, job.id, "error", error=str(e))
                _emit_batch(batch, {
                    "kind": "file_error",
                    "job_id": job.id,
                    "filename": job.filename,
                    "error": str(e),
                    "converted": batch.converted,
                    "skipped": batch.skipped,
                    "failed": batch.failed,
                    "total": batch.total,
                })
            else:
                job.queue.put(ProgressEvent(kind="error", message=str(e)))
        finally:
            if batch is not None:
                _finalize_batch_if_done(batch)
            else:
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
        ahead = sum(1 for j in jobs.values() if j.status in ("queued", "running") and j.batch_id is None)
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
    if job.staging_dir is None:
        raise HTTPException(status_code=400, detail="Este job no soporta descarga (batch)")

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


class BatchRequest(BaseModel):
    root_path: str
    options: dict = {}
    force: bool = False
    extensions: list[str] | None = None


_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@app.post("/convert-batch")
async def convert_batch(req: BatchRequest) -> dict:
    raw_path = req.root_path.strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="root_path es obligatorio")

    # Guard: path estilo Windows (C:\..., D:/...) en server no-Windows.
    if platform.system() != "Windows" and _WINDOWS_DRIVE_PATH.match(raw_path):
        drive = raw_path[0].lower()
        rest = raw_path[3:].replace("\\", "/")
        suggested = f"/mnt/{drive}/{rest}"
        raise HTTPException(
            status_code=400,
            detail=(
                f"Path estilo Windows ({raw_path!r}) en server {platform.system()}. "
                f"Si estás en WSL, usá la ruta montada: '{suggested}'."
            ),
        )

    try:
        opts = ConversionOptions(**req.options) if req.options else DEFAULT_OPTIONS
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Opciones inválidas: {e}")

    root = Path(raw_path).expanduser()
    try:
        root = root.resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No existe la ruta: {root}")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"No es un directorio: {root}")

    try:
        extensions = normalize_extensions(req.extensions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    output_root = default_batch_output_root(root)
    output_root.mkdir(parents=True, exist_ok=True)

    try:
        plan = plan_batch(root, output_root, extensions, force=req.force)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    batch_id = uuid.uuid4().hex
    batch = BatchSession(
        id=batch_id,
        root=root,
        output_root=output_root,
        options=opts,
        force=req.force,
        total=len(plan),
        job_ids=[],
    )

    queued_jobs: list[str] = []

    for item in plan:
        rel_source = str(item.source.relative_to(root))
        rel_output = str(item.output.relative_to(output_root))

        if item.action == "skip_existing":
            batch.skipped += 1
            batch.files.append({
                "job_id": None,
                "source": rel_source,
                "output": rel_output,
                "status": "skipped",
                "note": item.note,
            })
            continue

        if item.action == "skip_duplicate":
            batch.skipped += 1
            batch.files.append({
                "job_id": None,
                "source": rel_source,
                "output": rel_output,
                "status": "skipped_duplicate",
                "note": item.note,
            })
            continue

        item.output.parent.mkdir(parents=True, exist_ok=True)

        job_id = uuid.uuid4().hex
        job = Job(
            id=job_id,
            filename=item.source.name,
            input_path=item.source,
            output_path=item.output,
            staging_dir=None,
            batch_id=batch_id,
            options=opts,
        )

        with jobs_lock:
            jobs[job_id] = job

        batch.job_ids.append(job_id)
        queued_jobs.append(job_id)
        batch.files.append({
            "job_id": job_id,
            "source": rel_source,
            "output": rel_output,
            "status": "queued",
            "note": item.note,
        })

    batches[batch_id] = batch

    if batch.total == 0 or len(queued_jobs) == 0:
        _emit_batch(batch, {
            "kind": "batch_done",
            "message": (
                f"Sin archivos para procesar (total {batch.total}, "
                f"saltados {batch.skipped})."
            ),
            "total": batch.total,
            "converted": 0,
            "skipped": batch.skipped,
            "failed": 0,
        })
        batch.queue.put(None)
        batch.finished = True
    else:
        for jid in queued_jobs:
            job_queue.put(jid)

    return {
        "batch_id": batch_id,
        "root": str(root),
        "output_root": str(output_root),
        "total": batch.total,
        "queued": len(queued_jobs),
        "skipped": batch.skipped,
        "warning_mnt": is_wsl_windows_mount(root),
        "extensions": sorted(extensions),
        "files": batch.files,
    }


@app.get("/batch-progress/{batch_id}")
async def batch_progress(batch_id: str) -> EventSourceResponse:
    batch = batches.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch no encontrado")

    async def stream():
        while True:
            event = await asyncio.to_thread(batch.queue.get)
            if event is None:
                return
            yield {"event": event.get("kind", "message"), "data": json.dumps(event)}

    return EventSourceResponse(stream())


@app.get("/batch-status/{batch_id}")
async def batch_status(batch_id: str) -> dict:
    batch = batches.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch no encontrado")
    return {
        "batch_id": batch.id,
        "root": str(batch.root),
        "output_root": str(batch.output_root),
        "total": batch.total,
        "converted": batch.converted,
        "skipped": batch.skipped,
        "failed": batch.failed,
        "finished": batch.finished,
        "files": batch.files,
    }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _open_browser_when_ready(url: str) -> None:
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()


if __name__ == "__main__":
    import uvicorn

    HOST, PORT = "127.0.0.1", 8000
    _open_browser_when_ready(f"http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
