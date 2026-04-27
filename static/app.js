const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const states = {
  idle: document.getElementById("state-idle"),
  working: document.getElementById("state-working"),
  done: document.getElementById("state-done"),
  error: document.getElementById("state-error"),
};
const workingFilename = document.getElementById("working-filename");
const workingStatus = document.getElementById("working-status");
const queuedBanner = document.getElementById("queued-banner");
const queuedPosition = document.getElementById("queued-position");
const pageCounter = document.getElementById("page-counter");
const pageCurrent = document.getElementById("page-current");
const pageTotal = document.getElementById("page-total");
const progressWrap = document.getElementById("progress-wrap");
const progressFill = document.getElementById("progress-fill");
const progressDetail = document.getElementById("progress-detail");
const log = document.getElementById("log");
const errorMessage = document.getElementById("error-message");

document.getElementById("btn-reset").addEventListener("click", () => showState("idle"));
document.getElementById("btn-retry").addEventListener("click", () => showState("idle"));

function showState(name) {
  for (const key of Object.keys(states)) {
    states[key].classList.toggle("hidden", key !== name);
  }
  if (name === "idle") {
    log.innerHTML = "";
    progressFill.style.width = "0%";
    progressDetail.textContent = "Esperando inicio...";
    setWorkingMode("uploading");
  }
}

function setWorkingMode(mode) {
  // mode: "uploading" | "queued" | "converting"
  queuedBanner.classList.toggle("hidden", mode !== "queued");
  pageCounter.classList.toggle("hidden", mode !== "converting");
  progressWrap.classList.toggle("hidden", mode === "queued");
}

function appendLog(line) {
  const el = document.createElement("div");
  el.className = "log-line";
  el.textContent = line;
  log.appendChild(el);
  log.parentElement.scrollTop = log.parentElement.scrollHeight;
}

function triggerDownload(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function readOptions() {
  return {
    chunk_size: Math.max(1, parseInt(document.getElementById("opt-chunk-size").value, 10) || 1),
    max_retries: Math.max(0, parseInt(document.getElementById("opt-max-retries").value, 10) || 0),
    do_ocr: document.getElementById("opt-do-ocr").checked,
    table_mode: document.getElementById("opt-table-mode").value,
    num_threads: Math.max(1, parseInt(document.getElementById("opt-num-threads").value, 10) || 1),
  };
}

dropzone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (file) handleFile(file);
});

["dragenter", "dragover"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.add("dropzone-active");
  });
});
["dragleave", "drop"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("dropzone-active");
  });
});
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});

window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

async function handleFile(file) {
  showState("working");
  workingFilename.textContent = file.name;
  workingStatus.textContent = "Subiendo...";
  setWorkingMode("uploading");
  appendLog(`> Subiendo ${file.name} (${formatBytes(file.size)})`);

  const options = readOptions();
  const formData = new FormData();
  formData.append("file", file);
  formData.append("options", JSON.stringify(options));

  let jobId, downloadName, position;
  try {
    const res = await fetch("/convert", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Error al subir el archivo");
    }
    const data = await res.json();
    jobId = data.job_id;
    position = data.position || 0;
    downloadName = file.name.replace(/\.[^.]+$/, "") + ".md";
    appendLog(`> Job ${jobId.slice(0, 8)} encolado (posición ${position})`);
  } catch (err) {
    showError(err.message);
    return;
  }

  if (position > 0) {
    workingStatus.textContent = "En cola";
    queuedPosition.textContent = position;
    setWorkingMode("queued");
  } else {
    workingStatus.textContent = "Convirtiendo...";
    setWorkingMode("converting");
  }

  streamProgress(jobId, downloadName);
}

function streamProgress(jobId, downloadName) {
  const evt = new EventSource(`/progress/${jobId}`);
  let finished = false;

  const updateCounter = (current, total) => {
    if (typeof current === "number" && typeof total === "number" && total > 0) {
      pageCurrent.textContent = current;
      pageTotal.textContent = total;
      const pct = Math.round((current / total) * 100);
      progressFill.style.width = `${pct}%`;
      progressDetail.textContent = `${pct}% completado`;
    }
  };

  const handleQueued = (e) => {
    const data = JSON.parse(e.data);
    appendLog(`> ${data.message}`);
    queuedPosition.textContent = data.current ?? "-";
    setWorkingMode("queued");
    workingStatus.textContent = "En cola";
  };

  const handleInfo = (e) => {
    const data = JSON.parse(e.data);
    appendLog(`> ${data.message}`);
    workingStatus.textContent = "Convirtiendo...";
    setWorkingMode("converting");
    if (typeof data.total === "number" && data.total > 0) {
      pageTotal.textContent = data.total;
      pageCurrent.textContent = data.current ?? 0;
    }
  };

  const handlePageStart = (e) => {
    const data = JSON.parse(e.data);
    appendLog(`> ${data.message}`);
    setWorkingMode("converting");
    if (typeof data.current === "number" && typeof data.total === "number") {
      // current = paginas completadas; mostramos la "en proceso" como current+1
      pageCurrent.textContent = Math.min(data.current + 1, data.total);
      pageTotal.textContent = data.total;
      progressDetail.textContent = `Procesando página ${data.current + 1} de ${data.total}`;
    }
  };

  const handlePageDone = (e) => {
    const data = JSON.parse(e.data);
    updateCounter(data.current, data.total);
  };

  const handleRetryWarning = (e) => {
    const data = JSON.parse(e.data);
    appendLog(`> ⚠ ${data.message}`);
  };

  const handleError = (e) => {
    const data = JSON.parse(e.data);
    finished = true;
    evt.close();
    showError(data.message);
  };

  evt.addEventListener("queued", handleQueued);
  evt.addEventListener("info", handleInfo);
  evt.addEventListener("page_start", handlePageStart);
  evt.addEventListener("page_done", handlePageDone);
  evt.addEventListener("retry", handleRetryWarning);
  evt.addEventListener("warning", handleRetryWarning);
  evt.addEventListener("error", handleError);

  evt.addEventListener("done", (e) => {
    finished = true;
    progressFill.style.width = "100%";
    pageCurrent.textContent = pageTotal.textContent;
    progressDetail.textContent = "Conversión completada";
    appendLog("> ✓ Conversión completada");
    setTimeout(() => {
      evt.close();
      triggerDownload(`/download/${jobId}`, downloadName);
      showState("done");
    }, 600);
  });

  evt.onerror = () => {
    if (!finished) {
      evt.close();
      showError("La conexión con el servidor se interrumpió");
    }
  };
}

function showError(message) {
  errorMessage.textContent = message;
  showState("error");
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
