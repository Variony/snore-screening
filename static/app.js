const fileInput = document.querySelector("#audio-file");
const analyzeButton = document.querySelector("#analyze");
const selectedFile = document.querySelector("#selected-file");
const errorBox = document.querySelector("#error");
const progressArea = document.querySelector("#progress-area");
const progressBar = document.querySelector("#progress");
const statusText = document.querySelector("#status");
const percentText = document.querySelector("#percent");
const resultsSection = document.querySelector("#results");
const player = document.querySelector("#player");
const downloadResultsButton = document.querySelector("#download-results");
const languageButton = document.querySelector("#language-toggle");
const translations = {
  en: {
    languageAria: "Switch language to Chinese",
    eyebrow: "LOCAL · STREAMING SCAN",
    appTitle: "Snore Screening",
    intro: "Find possible sudden increases in snoring or breathing volume and preview them. This screens loudness only; it does not identify sound sources.",
    chooseFile: "Choose an audio file",
    supportedFormats: "WAV supported; install FFmpeg for MP3, M4A, AAC, FLAC, OGG, and more",
    minimumPeak: "Minimum peak",
    minimumPeakHint: "Lower values may catch quieter snores but increase false positives",
    riseAboveBackground: "Rise above background",
    riseHint: "Minimum increase compared with recent background",
    windowSize: "Window size",
    windowHint: "Suitable for changes lasting a few hundred milliseconds",
    startScan: "Start scan",
    ready: "Ready",
    privacy: "The file is sent only to this computer for analysis. Its temporary copy is deleted afterward. The original is not modified or uploaded to the internet.",
    scanResults: "SCAN RESULTS",
    foundCandidates: ({ count }) => `Found ${count} candidate${count === 1 ? "" : "s"}`,
    downloadAudioZip: "Download candidate audio ZIP",
    downloadReportZip: "Download scan report ZIP",
    resultHint: "Select a row to play from about 3 seconds before the event. These are loudness-spike candidates and may include other sounds.",
    time: "Time",
    duration: "Duration",
    peak: "Peak",
    rise: "Rise",
    preview: "Preview",
    noFindings: "No loudness spikes matched these settings. Try lowering the peak or rise threshold.",
    playerLabel: "Audio player",
    disclaimer: "This tool is for reviewing audio only, not for medical advice or diagnosis. Results depend on recording levels and selected thresholds.",
    footer: "Snore Screening · Runs only on this computer",
    seconds: "sec",
    listen: "Listen",
    candidateAria: ({ index, time }) => `Listen to candidate ${index} at ${time}`,
    uploading: "Uploading audio to this computer…",
    uploadComplete: "Upload complete; starting scan…",
    uploadPercent: ({ percent }) => `Upload ${percent}%`,
    analyzing: "Scanning audio…",
    analysisPercent: ({ percent }) => `Scan ${percent}%`,
    analysisTime: ({ processed, total }) => `Scanned ${processed} of ${total}`,
    packaging: "Creating candidate audio clips…",
    packagingPercent: ({ percent }) => `Packaging ${percent}%`,
    complete: "Scan and packaging complete",
    waiting: "Upload received; starting scan…",
    progressUnavailable: "Scanning locally; progress is temporarily unavailable…",
    connectionError: "Cannot connect to the local analysis service. Check that it is still running, then refresh the page.",
    unreadableResult: "The local service returned an unreadable result.",
    scanFailed: "Scan failed.",
  },
  zh: {
    languageAria: "切换语言为英文",
    eyebrow: "完全本地 · 逐块扫描",
    appTitle: "呼噜筛查",
    intro: "筛查呼噜声、呼吸声中突然变响的候选片段并试听。工具只按响度变化筛查，不判断声源。",
    chooseFile: "选择音频文件",
    supportedFormats: "支持 WAV；安装 FFmpeg 后也支持 MP3、M4A、AAC、FLAC、OGG 等格式",
    minimumPeak: "最低峰值",
    minimumPeakHint: "门槛调低可找到较轻的鼾声，也会增加误报",
    riseAboveBackground: "高于背景的幅度",
    riseHint: "比近期背景至少高出此幅度",
    windowSize: "检测窗口",
    windowHint: "适合筛查持续数百毫秒的响声变化",
    startScan: "开始扫描",
    ready: "准备中…",
    privacy: "文件仅发送到本机应用进行分析，服务器使用的临时副本会在分析结束后删除。原始录音不会被修改，也不会上传到互联网。",
    scanResults: "扫描结果",
    foundCandidates: ({ count }) => `发现 ${count} 处`,
    downloadAudioZip: "下载候选音频 ZIP",
    downloadReportZip: "下载扫描报告 ZIP",
    resultHint: "选择一行可从该片段前约 3 秒开始试听。结果是响度突增候选，可能也包含其他声音。",
    time: "时间",
    duration: "持续",
    peak: "峰值",
    rise: "响度增幅",
    preview: "试听",
    noFindings: "没有发现符合当前门槛的突发大声片段。可尝试降低最低峰值或减小增幅门槛。",
    playerLabel: "音频播放器",
    disclaimer: "本工具仅用于声音片段回顾，不提供医疗建议或诊断。检测结果取决于录音电平和所选门槛。",
    footer: "呼噜筛查 · 仅在此电脑运行",
    seconds: "秒",
    listen: "试听",
    candidateAria: ({ index, time }) => `试听第 ${index} 处，${time}`,
    uploading: "正在将文件上传到本机…",
    uploadComplete: "上传完成，正在开始扫描…",
    uploadPercent: ({ percent }) => `上传 ${percent}%`,
    analyzing: "正在扫描音频…",
    analysisPercent: ({ percent }) => `扫描 ${percent}%`,
    analysisTime: ({ processed, total }) => `已扫描 ${processed} / ${total}`,
    packaging: "正在生成候选音频片段…",
    packagingPercent: ({ percent }) => `打包 ${percent}%`,
    complete: "扫描和打包完成",
    waiting: "文件已接收，正在开始扫描…",
    progressUnavailable: "正在本机扫描，暂时无法获取进度…",
    connectionError: "无法连接本机分析服务。请确认运行窗口中的服务仍在运行，然后刷新页面。",
    unreadableResult: "本机服务返回了无法读取的结果。",
    scanFailed: "扫描失败。",
  },
};
let language = "en";
let previewUrl = null;
let request = null;
let lastAnalysis = null;
let progressTimer = null;
let currentProgressState = null;

try {
  language = localStorage.getItem("snore-screening-language") === "zh" ? "zh" : "en";
} catch {}

languageButton.addEventListener("click", () => {
  language = language === "en" ? "zh" : "en";
  try { localStorage.setItem("snore-screening-language", language); } catch {}
  applyLanguage();
});
applyLanguage();

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  analyzeButton.disabled = !file;
  downloadResultsButton.disabled = true;
  lastAnalysis = null;
  selectedFile.hidden = !file;
  selectedFile.textContent = file ? `${file.name} · ${formatBytes(file.size)}` : "";
  errorBox.hidden = true;
});

analyzeButton.addEventListener("click", () => {
  const file = fileInput.files[0];
  if (!file) return;
  errorBox.hidden = true;
  resultsSection.hidden = true;
  downloadResultsButton.disabled = true;
  lastAnalysis = null;
  currentProgressState = { stage: "uploading", percent: 0 };
  analyzeButton.disabled = true;
  progressArea.hidden = false;
  progressBar.value = 0;
  renderProgress();

  const params = new URLSearchParams({
    min_peak_dbfs: document.querySelector("#min-peak").value,
    rise_db: document.querySelector("#rise").value,
    window_ms: document.querySelector("#window").value,
  });
  request = new XMLHttpRequest();
  request.open("POST", `/api/analyze?${params}`);
  const extension = file.name.match(/\.[a-z0-9]{1,10}$/i)?.[0] || ".audio";
  request.setRequestHeader("X-Audio-Filename", `audio${extension}`);
  request.setRequestHeader("X-Audio-Display-Name", encodeURIComponent(file.name));
  request.setRequestHeader("X-UI-Language", language);
  const analysisId = createAnalysisId();
  request.setRequestHeader("X-Analysis-ID", analysisId);
  request.upload.addEventListener("progress", event => {
    if (!event.lengthComputable) return;
    const percent = Math.floor(event.loaded / event.total * 100);
    currentProgressState = { stage: "uploading", percent };
    renderProgress();
  });
  request.upload.addEventListener("load", () => {
    currentProgressState = { stage: "uploading", percent: 100 };
    renderProgress();
    startProgressPolling(analysisId);
  }, { once: true });
  const currentRequest = request;
  currentRequest.addEventListener("load", () => {
    stopProgressPolling();
    request = null;
    analyzeButton.disabled = false;
    if (currentRequest.status < 200 || currentRequest.status >= 300) {
      let message = t("scanFailed");
      try { message = JSON.parse(currentRequest.responseText).error || message; } catch {}
      progressArea.hidden = true;
      showError(message);
      return;
    }
    try {
      const result = JSON.parse(currentRequest.responseText);
      currentProgressState = { stage: "complete", percent: 100 };
      renderProgress();
      renderResults(result, file);
    } catch {
      progressArea.hidden = true;
      showError(t("unreadableResult"));
    }
  }, { once: true });
  currentRequest.addEventListener("error", () => {
    stopProgressPolling();
    request = null;
    analyzeButton.disabled = false;
    progressArea.hidden = true;
    showError(t("connectionError"));
  }, { once: true });
  currentRequest.send(file);
});

downloadResultsButton.addEventListener("click", () => {
  if (!lastAnalysis?.download_id) return;
  const link = document.createElement("a");
  link.href = `/api/results.zip?id=${encodeURIComponent(lastAnalysis.download_id)}`;
  link.download = "snore_screening_results.zip";
  document.body.append(link);
  link.click();
  link.remove();
});

function renderResults(result, file) {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  player.src = previewUrl;
  lastAnalysis = result;
  downloadResultsButton.disabled = !result.download_id;
  downloadResultsButton.textContent = t(
    result.events.length ? "downloadAudioZip" : "downloadReportZip"
  );
  const findings = document.querySelector("#findings");
  findings.replaceChildren();
  document.querySelector("#summary").textContent = t("foundCandidates", { count: result.events.length });
  document.querySelector("#duration").textContent = `${formatTime(result.duration)} · ${formatBytes(result.file_size)}`;
  document.querySelector("#no-findings").hidden = result.events.length !== 0;

  result.events.forEach((event, index) => {
    const row = document.createElement("tr");
    const duration = (event.end - event.start).toFixed(1);
    row.innerHTML = `<td>${formatTime(event.start)} – ${formatTime(event.end)}</td>
      <td class="event-duration">${duration} ${t("seconds")}</td>
      <td>${event.peak_dbfs.toFixed(1)} dBFS</td>
      <td>+${event.rise_db.toFixed(1)} dB</td>
      <td><button class="play-link" type="button">${t("listen")}</button></td>`;
    row.querySelector("button").addEventListener("click", eventClick => {
      eventClick.stopPropagation();
      playFinding(event.start);
    });
    row.addEventListener("click", () => playFinding(event.start));
    row.dataset.index = index + 1;
    row.dataset.start = event.start;
    row.dataset.duration = duration;
    row.setAttribute("aria-label", t("candidateAria", {
      index: index + 1,
      time: formatTime(event.start),
    }));
    findings.append(row);
  });
  resultsSection.hidden = false;
}

function startProgressPolling(analysisId) {
  stopProgressPolling();
  let pending = false;
  const poll = async () => {
    if (pending) return;
    pending = true;
    try {
      const response = await fetch(`/api/progress?id=${encodeURIComponent(analysisId)}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        currentProgressState = { stage: response.status === 404 ? "waiting" : "unavailable" };
        renderProgress();
        return;
      }
      currentProgressState = await response.json();
      renderProgress();
    } catch {
      currentProgressState = { stage: "unavailable" };
      renderProgress();
    } finally {
      pending = false;
    }
  };
  void poll();
  progressTimer = setInterval(poll, 700);
}

function stopProgressPolling() {
  if (progressTimer !== null) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
}

function t(key, values = {}) {
  const translation = translations[language][key];
  return typeof translation === "function" ? translation(values) : translation || key;
}

function applyLanguage() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  document.title = t("appTitle");
  document.querySelectorAll("[data-i18n]").forEach(element => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-aria]").forEach(element => {
    element.setAttribute("aria-label", t(element.dataset.i18nAria));
  });
  languageButton.textContent = language === "en" ? "中文" : "English";
  languageButton.setAttribute("aria-label", t("languageAria"));

  if (lastAnalysis) {
    document.querySelector("#summary").textContent = t("foundCandidates", {
      count: lastAnalysis.events.length,
    });
    downloadResultsButton.textContent = t(
      lastAnalysis.events.length ? "downloadAudioZip" : "downloadReportZip"
    );
    document.querySelectorAll("#findings tr").forEach(row => {
      row.querySelector(".play-link").textContent = t("listen");
      row.querySelector(".event-duration").textContent =
        `${row.dataset.duration} ${t("seconds")}`;
      row.setAttribute("aria-label", t("candidateAria", {
        index: row.dataset.index,
        time: formatTime(Number(row.dataset.start)),
      }));
    });
  } else {
    document.querySelector("#summary").textContent = t("foundCandidates", { count: 0 });
  }
  renderProgress();
}

function renderProgress() {
  if (!currentProgressState) return;
  const state = currentProgressState;
  const percent = Math.max(0, Math.min(100, Number(state.percent) || 0));
  if (state.stage === "uploading") {
    progressBar.value = percent * 0.2;
    percentText.textContent = t("uploadPercent", { percent });
    statusText.textContent = percent >= 100 ? t("uploadComplete") : t("uploading");
  } else if (state.stage === "analyzing") {
    progressBar.value = 20 + percent * 0.8;
    percentText.textContent = t("analysisPercent", { percent });
    statusText.textContent = t("analysisTime", {
      processed: formatTime(state.processed_seconds || 0),
      total: formatTime(state.total_seconds || 0),
    });
  } else if (state.stage === "packaging") {
    progressBar.value = 20 + percent * 0.8;
    percentText.textContent = t("packagingPercent", { percent });
    statusText.textContent = t("packaging");
  } else if (state.stage === "complete") {
    progressBar.value = 100;
    percentText.textContent = t("analysisPercent", { percent: 100 });
    statusText.textContent = t("complete");
  } else if (state.stage === "waiting") {
    progressBar.value = 20;
    percentText.textContent = t("uploadComplete");
    statusText.textContent = t("waiting");
  } else if (state.stage === "unavailable") {
    statusText.textContent = t("progressUnavailable");
  } else if (state.stage === "error") {
    statusText.textContent = t("scanFailed");
  }
}

function playFinding(start) {
  if (!player.src) return;
  player.currentTime = Math.max(0, start - 3);
  player.play().catch(() => {});
  player.scrollIntoView({ behavior: "smooth", block: "center" });
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function formatTime(seconds) {
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const fraction = Math.floor((seconds - total) * 10);
  return `${hours ? `${hours}:` : ""}${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${fraction}`;
}

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(unit > 0 ? 1 : 0)} ${units[unit]}`;
}

function createAnalysisId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map(byte => byte.toString(16).padStart(2, "0"))
    .join("");
}
