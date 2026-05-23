const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const states = {
  idle: document.getElementById("state-idle"),
  "batch-idle": document.getElementById("state-batch-idle"),
  working: document.getElementById("state-working"),
  "batch-working": document.getElementById("state-batch-working"),
  done: document.getElementById("state-done"),
  "batch-done": document.getElementById("state-batch-done"),
  error: document.getElementById("state-error"),
};
const tabs = document.querySelectorAll(".tab-btn");
const tabsBar = document.getElementById("tabs");
let activeTab = "file";
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

document.getElementById("btn-reset").addEventListener("click", () => showIdleForActiveTab());
document.getElementById("btn-retry").addEventListener("click", () => showIdleForActiveTab());
document.getElementById("btn-batch-reset").addEventListener("click", () => showIdleForActiveTab());

tabs.forEach((btn) => {
  btn.addEventListener("click", () => {
    activeTab = btn.dataset.tab;
    tabs.forEach((b) => {
      const isActive = b.dataset.tab === activeTab;
      b.classList.toggle("border-indigo-600", isActive);
      b.classList.toggle("text-indigo-600", isActive);
      b.classList.toggle("font-semibold", isActive);
      b.classList.toggle("border-transparent", !isActive);
      b.classList.toggle("text-slate-500", !isActive);
      b.classList.toggle("font-medium", !isActive);
    });
    showIdleForActiveTab();
  });
});

function showIdleForActiveTab() {
  showState(activeTab === "batch" ? "batch-idle" : "idle");
}

function showState(name) {
  for (const key of Object.keys(states)) {
    states[key].classList.toggle("hidden", key !== name);
  }
  // Tabs solo visibles en estados idle
  const isIdleLike = name === "idle" || name === "batch-idle";
  tabsBar.classList.toggle("hidden", !isIdleLike);

  if (name === "idle") {
    log.innerHTML = "";
    progressFill.style.width = "0%";
    progressDetail.textContent = "Esperando inicio...";
    setWorkingMode("uploading");
  }
  if (name === "batch-idle") {
    resetBatchUI();
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

// =====================================================================
// BATCH MODE
// =====================================================================

const batchRoot = document.getElementById("batch-root");
const batchForce = document.getElementById("batch-force");
const batchStart = document.getElementById("batch-start");
const batchMntWarning = document.getElementById("batch-mnt-warning");
const batchExtCheckboxes = document.querySelectorAll(".batch-ext");
const batchExtEmptyWarning = document.getElementById("batch-ext-empty-warning");
const batchExtOnlyPdf = document.getElementById("batch-ext-only-pdf");
const batchExtAll = document.getElementById("batch-ext-all");
const batchRootLabel = document.getElementById("batch-root-label");
const batchProgressFill = document.getElementById("batch-progress-fill");
const batchCounterDone = document.getElementById("batch-counter-done");
const batchCounterTotal = document.getElementById("batch-counter-total");
const batchStatConverted = document.getElementById("batch-stat-converted");
const batchStatSkipped = document.getElementById("batch-stat-skipped");
const batchStatFailed = document.getElementById("batch-stat-failed");
const batchCurrentFile = document.getElementById("batch-current-file");
const batchCurrentDetail = document.getElementById("batch-current-detail");
const batchCurrentPct = document.getElementById("batch-current-pct");
const batchCurrentProgressWrap = document.getElementById("batch-current-progress-wrap");
const batchCurrentProgressFill = document.getElementById("batch-current-progress-fill");
const batchFileList = document.getElementById("batch-file-list");
const batchLog = document.getElementById("batch-log");
const batchDoneSummary = document.getElementById("batch-done-summary");
const batchDoneOutput = document.getElementById("batch-done-output");

const STATUS_BADGE = {
  queued: { label: "en cola", cls: "bg-slate-100 text-slate-600" },
  running: { label: "procesando", cls: "bg-indigo-100 text-indigo-700" },
  done: { label: "ok", cls: "bg-green-100 text-green-700" },
  error: { label: "error", cls: "bg-red-100 text-red-700" },
  skipped: { label: "saltado", cls: "bg-slate-100 text-slate-500" },
  skipped_duplicate: { label: "duplicado", cls: "bg-amber-100 text-amber-700" },
};

let batchFileItems = new Map(); // job_id -> li element ; "skipped:N" para skipped sin job_id
const ACTIVE_BATCH_KEY = "docling.activeBatch";

function resetBatchUI() {
  batchProgressFill.style.width = "0%";
  batchCounterDone.textContent = "0";
  batchCounterTotal.textContent = "0";
  batchStatConverted.textContent = "0";
  batchStatSkipped.textContent = "0";
  batchStatFailed.textContent = "0";
  batchCurrentFile.textContent = "—";
  batchCurrentDetail.textContent = "Esperando inicio...";
  batchCurrentPct.textContent = "0%";
  batchCurrentPct.classList.add("hidden");
  batchCurrentProgressWrap.classList.add("hidden");
  batchCurrentProgressFill.style.width = "0%";
  batchFileList.innerHTML = "";
  batchLog.innerHTML = "";
  batchFileItems = new Map();
  batchMntWarning.classList.add("hidden");
}

function setCurrentFilePct(pct) {
  const clamped = Math.max(0, Math.min(100, pct));
  batchCurrentPct.textContent = `${clamped}%`;
  batchCurrentPct.classList.remove("hidden");
  batchCurrentProgressWrap.classList.remove("hidden");
  batchCurrentProgressFill.style.width = `${clamped}%`;
}

function clearCurrentFilePct() {
  batchCurrentPct.classList.add("hidden");
  batchCurrentProgressWrap.classList.add("hidden");
  batchCurrentProgressFill.style.width = "0%";
}

function setRunningBadge(jobId, pct) {
  const item = batchFileItems.get(jobId);
  if (!item) return;
  const meta = STATUS_BADGE.running;
  item.badge.className = `px-2 py-0.5 rounded-full text-[10px] font-semibold ${meta.cls}`;
  item.badge.textContent = typeof pct === "number" ? `${meta.label} ${pct}%` : meta.label;
}

function batchAppendLog(line) {
  const el = document.createElement("div");
  el.className = "log-line";
  el.textContent = line;
  batchLog.appendChild(el);
  batchLog.parentElement.scrollTop = batchLog.parentElement.scrollHeight;
}

function readBatchOptions() {
  return {
    chunk_size: Math.max(1, parseInt(document.getElementById("batch-chunk-size").value, 10) || 1),
    max_retries: Math.max(0, parseInt(document.getElementById("batch-max-retries").value, 10) || 0),
    do_ocr: document.getElementById("batch-do-ocr").checked,
    table_mode: document.getElementById("batch-table-mode").value,
    num_threads: Math.max(1, parseInt(document.getElementById("batch-num-threads").value, 10) || 1),
  };
}

batchRoot.addEventListener("input", () => {
  const v = batchRoot.value.trim();
  // Aviso temprano si el path apunta al FS de Windows
  batchMntWarning.classList.toggle("hidden", !v.startsWith("/mnt/"));
});

batchExtCheckboxes.forEach((cb) => {
  cb.addEventListener("change", () => batchExtEmptyWarning.classList.add("hidden"));
});

batchExtOnlyPdf.addEventListener("click", () => {
  batchExtCheckboxes.forEach((cb) => { cb.checked = cb.value === "pdf"; });
  batchExtEmptyWarning.classList.add("hidden");
});

batchExtAll.addEventListener("click", () => {
  batchExtCheckboxes.forEach((cb) => { cb.checked = true; });
  batchExtEmptyWarning.classList.add("hidden");
});

function readBatchExtensions() {
  const out = [];
  batchExtCheckboxes.forEach((cb) => {
    if (cb.checked) out.push(cb.value);
  });
  return out;
}

batchStart.addEventListener("click", startBatch);

function renderFileRow(file) {
  const row = document.createElement("div");
  row.className = "px-3 py-1.5 flex items-center justify-between gap-2";
  const left = document.createElement("span");
  left.className = "mono truncate text-slate-700 flex-1";
  left.textContent = file.source;
  left.title = `${file.source} → ${file.output}`;
  const badge = document.createElement("span");
  const meta = STATUS_BADGE[file.status] || STATUS_BADGE.queued;
  badge.className = `px-2 py-0.5 rounded-full text-[10px] font-semibold ${meta.cls}`;
  badge.textContent = meta.label;
  row.appendChild(left);
  row.appendChild(badge);
  batchFileList.appendChild(row);
  return { row, badge };
}

function updateFileBadge(jobId, status) {
  const item = batchFileItems.get(jobId);
  if (!item) return;
  const meta = STATUS_BADGE[status] || STATUS_BADGE.queued;
  item.badge.className = `px-2 py-0.5 rounded-full text-[10px] font-semibold ${meta.cls}`;
  item.badge.textContent = meta.label;
}

async function startBatch() {
  const rootPath = batchRoot.value.trim();
  if (!rootPath) {
    batchAppendLog("> Falta ingresar la ruta de la carpeta");
    return;
  }

  const extensions = readBatchExtensions();
  if (extensions.length === 0) {
    batchExtEmptyWarning.classList.remove("hidden");
    return;
  }

  resetBatchUI();
  showState("batch-working");
  batchRootLabel.textContent = rootPath;
  batchAppendLog(`> Descubriendo archivos (${extensions.join(", ")}) en ${rootPath}...`);

  let data;
  try {
    const res = await fetch("/convert-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        root_path: rootPath,
        options: readBatchOptions(),
        force: batchForce.checked,
        extensions: extensions,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Error al iniciar batch");
    }
    data = await res.json();
  } catch (err) {
    showError(err.message);
    return;
  }

  batchCounterTotal.textContent = data.total;
  batchStatSkipped.textContent = data.skipped;
  if (data.warning_mnt) {
    batchMntWarning.classList.remove("hidden");
    batchAppendLog("> ⚠ Path en /mnt/ — la lectura será lenta");
  }
  const extLabel = (data.extensions || []).join(", ") || "archivos";
  batchAppendLog(`> ${data.total} archivos (${extLabel}) · ${data.queued} a procesar · ${data.skipped} saltados`);

  let skippedCounter = 0;
  data.files.forEach((file) => {
    const item = renderFileRow(file);
    const key = file.job_id || `skipped:${skippedCounter++}`;
    batchFileItems.set(key, item);
  });

  if (data.queued === 0) {
    finishBatch(data);
    return;
  }

  saveActiveBatch({
    batch_id: data.batch_id,
    root: data.root,
    output_root: data.output_root,
  });

  streamBatch(data);
}

function saveActiveBatch(info) {
  try {
    localStorage.setItem(ACTIVE_BATCH_KEY, JSON.stringify(info));
  } catch (_) {
    // localStorage no disponible (modo privado, etc) — sigue funcionando sin reconnect
  }
}

function clearActiveBatch() {
  try {
    localStorage.removeItem(ACTIVE_BATCH_KEY);
  } catch (_) {
    // ignorar
  }
}

function readActiveBatch() {
  try {
    const raw = localStorage.getItem(ACTIVE_BATCH_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

function streamBatch(batchInfo) {
  const evt = new EventSource(`/batch-progress/${batchInfo.batch_id}`);
  let finished = false;

  const refreshProgress = (converted, skipped, failed, total) => {
    const done = (converted || 0) + (skipped || 0) + (failed || 0);
    batchCounterDone.textContent = done;
    batchStatConverted.textContent = converted || 0;
    batchStatSkipped.textContent = skipped || 0;
    batchStatFailed.textContent = failed || 0;
    if (total > 0) {
      batchProgressFill.style.width = `${Math.round((done / total) * 100)}%`;
    }
  };

  evt.addEventListener("file_start", (e) => {
    const d = JSON.parse(e.data);
    batchCurrentFile.textContent = d.filename;
    batchCurrentDetail.textContent = "Procesando...";
    clearCurrentFilePct();
    updateFileBadge(d.job_id, "running");
    batchAppendLog(`> [START] ${d.filename}`);
  });

  evt.addEventListener("file_progress", (e) => {
    const d = JSON.parse(e.data);
    if (d.inner_kind === "page_start" && typeof d.current === "number" && typeof d.total === "number" && d.total > 0) {
      const currentPage = d.current + 1;
      const pct = Math.round((d.current / d.total) * 100);
      batchCurrentDetail.textContent = `Página ${currentPage} de ${d.total}`;
      setCurrentFilePct(pct);
      setRunningBadge(d.job_id, pct);
    } else if (d.inner_kind === "page_done" && typeof d.current === "number" && typeof d.total === "number" && d.total > 0) {
      const pct = Math.round((d.current / d.total) * 100);
      setCurrentFilePct(pct);
      setRunningBadge(d.job_id, pct);
    } else if (d.inner_kind === "info" && d.message) {
      batchCurrentDetail.textContent = d.message;
    } else if (d.inner_kind === "retry" || d.inner_kind === "warning") {
      batchAppendLog(`> ⚠ ${d.filename}: ${d.message}`);
    }
  });

  evt.addEventListener("file_done", (e) => {
    const d = JSON.parse(e.data);
    updateFileBadge(d.job_id, "done");
    refreshProgress(d.converted, d.skipped, d.failed, d.total);
    clearCurrentFilePct();
    batchAppendLog(`> ✓ ${d.filename}`);
  });

  evt.addEventListener("file_error", (e) => {
    const d = JSON.parse(e.data);
    updateFileBadge(d.job_id, "error");
    refreshProgress(d.converted, d.skipped, d.failed, d.total);
    clearCurrentFilePct();
    batchAppendLog(`> ✗ ${d.filename}: ${d.error}`);
  });

  evt.addEventListener("batch_done", (e) => {
    const d = JSON.parse(e.data);
    finished = true;
    refreshProgress(d.converted, d.skipped, d.failed, d.total);
    clearCurrentFilePct();
    batchAppendLog(`> ${d.message}`);
    clearActiveBatch();
    setTimeout(() => {
      evt.close();
      finishBatch({
        ...batchInfo,
        converted: d.converted,
        skipped: d.skipped,
        failed: d.failed,
      });
    }, 600);
  });

  evt.onerror = () => {
    if (!finished) {
      evt.close();
      showError("La conexión con el servidor se interrumpió");
    }
  };
}

function finishBatch(data) {
  const converted = data.converted ?? 0;
  const skipped = data.skipped ?? 0;
  const failed = data.failed ?? 0;
  batchDoneSummary.textContent = `${converted} convertidos · ${skipped} saltados · ${failed} errores`;
  batchDoneOutput.textContent = data.output_root || "";
  clearActiveBatch();
  showState("batch-done");
}

// =====================================================================
// AUTO-RECONNECT: si quedó un batch activo en localStorage al cargar
// la página, reconstruimos la UI desde /batch-status y nos volvemos a
// suscribir a /batch-progress.
// =====================================================================

async function tryReconnectBatch() {
  const stored = readActiveBatch();
  if (!stored || !stored.batch_id) return;

  let status;
  try {
    const res = await fetch(`/batch-status/${stored.batch_id}`);
    if (!res.ok) {
      clearActiveBatch();
      return;
    }
    status = await res.json();
  } catch (_) {
    return;
  }

  // Si el batch ya terminó, mostrar el done state y limpiar.
  if (status.finished) {
    finishBatch({
      root: status.root,
      output_root: status.output_root,
      converted: status.converted,
      skipped: status.skipped,
      failed: status.failed,
    });
    return;
  }

  // Activar la tab "batch" visualmente.
  activeTab = "batch";
  tabs.forEach((b) => {
    const isActive = b.dataset.tab === "batch";
    b.classList.toggle("border-indigo-600", isActive);
    b.classList.toggle("text-indigo-600", isActive);
    b.classList.toggle("font-semibold", isActive);
    b.classList.toggle("border-transparent", !isActive);
    b.classList.toggle("text-slate-500", !isActive);
    b.classList.toggle("font-medium", !isActive);
  });

  resetBatchUI();
  showState("batch-working");

  batchRootLabel.textContent = status.root;
  batchCounterTotal.textContent = status.total;
  batchAppendLog(`> Reconectado al batch ${stored.batch_id.slice(0, 8)}`);
  batchAppendLog(`> ${status.total} archivos · ${status.converted} convertidos · ${status.skipped} saltados · ${status.failed} errores hasta ahora`);

  let skippedCounter = 0;
  let runningFile = null;
  (status.files || []).forEach((file) => {
    const item = renderFileRow(file);
    const key = file.job_id || `skipped:${skippedCounter++}`;
    batchFileItems.set(key, item);
    if (file.status === "running") {
      runningFile = file;
    }
  });

  if (runningFile) {
    batchCurrentFile.textContent = (runningFile.source || "").split("/").pop();
    batchCurrentDetail.textContent = "Procesando (reconectado)...";
  }

  const done = (status.converted || 0) + (status.skipped || 0) + (status.failed || 0);
  batchCounterDone.textContent = done;
  batchStatConverted.textContent = status.converted || 0;
  batchStatSkipped.textContent = status.skipped || 0;
  batchStatFailed.textContent = status.failed || 0;
  if (status.total > 0) {
    batchProgressFill.style.width = `${Math.round((done / status.total) * 100)}%`;
  }

  streamBatch({
    batch_id: stored.batch_id,
    root: status.root,
    output_root: status.output_root,
    converted: status.converted,
    skipped: status.skipped,
    failed: status.failed,
  });
}

tryReconnectBatch();
