const state = {
  token: window.localStorage.getItem("meeting_ai_token") || "",
  user: null,
  meetings: [],
  selectedMeetingId: null,
  detailsTab: "overview",
  transcriptQuery: "",
  timelineSpeaker: "",
  busy: false,
};

const SESSION_EXPIRED_MESSAGE = "Session expired or invalid token. Please log in again.";
const MAX_UPLOAD_SIZE_MB = 25;
const MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024;
const ALLOWED_UPLOAD_EXTENSIONS = new Set([
  ".wav",
  ".mp3",
  ".m4a",
  ".mp4",
  ".mpeg",
  ".mpga",
  ".webm",
  ".ogg",
]);
const ALLOWED_UPLOAD_MIME_TYPES = new Set([
  "audio/wav",
  "audio/x-wav",
  "audio/wave",
  "audio/mpeg",
  "audio/mp3",
  "audio/mp4",
  "audio/x-m4a",
  "audio/m4a",
  "audio/webm",
  "audio/ogg",
  "application/ogg",
  "video/mp4",
]);

const processingPoll = {
  timerId: null,
  inFlight: false,
  meetingId: null,
};

const els = {
  userChip: document.getElementById("userChip"),
  statusLog: document.getElementById("statusLog"),
  emailInput: document.getElementById("emailInput"),
  passwordInput: document.getElementById("passwordInput"),
  registerBtn: document.getElementById("registerBtn"),
  loginBtn: document.getElementById("loginBtn"),
  logoutBtn: document.getElementById("logoutBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  createMeetingForm: document.getElementById("createMeetingForm"),
  meetingTitleInput: document.getElementById("meetingTitleInput"),
  meetingList: document.getElementById("meetingList"),
  meetingDetails: document.getElementById("meetingDetails"),
  meetingDetailsTemplate: document.getElementById("meetingDetailsTemplate"),
};

function log(message, type = "info") {
  const timestamp = new Date().toLocaleTimeString();
  const line = `[${timestamp}] ${message}`;
  const previous = els.statusLog.textContent.trim();
  const next = previous ? `${line}\n${previous}` : line;
  els.statusLog.textContent = next;
  if (type === "error") {
    console.error(message);
  } else {
    console.log(message);
  }
}

function setToken(token) {
  state.token = token || "";
  if (state.token) {
    window.localStorage.setItem("meeting_ai_token", state.token);
  } else {
    window.localStorage.removeItem("meeting_ai_token");
  }
}

function resetSession() {
  clearProcessingPoll();
  setToken("");
  state.user = null;
  state.meetings = [];
  state.selectedMeetingId = null;
  state.detailsTab = "overview";
  state.transcriptQuery = "";
  state.timelineSpeaker = "";
  render();
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const isFormData = options.body instanceof FormData;

  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (state.token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }

  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (response.status === 401) {
    resetSession();
    throw new Error(SESSION_EXPIRED_MESSAGE);
  }

  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload
      ? payload.detail
      : String(payload || `HTTP ${response.status}`);
    throw new Error(detail);
  }

  return payload;
}

function formatDate(value, emptyLabel = "Not available") {
  if (!value) return emptyLabel;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function formatBytes(value) {
  if (value == null) return "Unknown";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let size = value / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[unitIndex]}`;
}

function fileExtension(filename) {
  const dotIndex = filename.lastIndexOf(".");
  if (dotIndex < 0) return "";
  return filename.slice(dotIndex).toLowerCase();
}

function validateUploadCandidate(file) {
  const extension = fileExtension(file.name || "");
  if (!extension) {
    return "File extension is required.";
  }
  if (!ALLOWED_UPLOAD_EXTENSIONS.has(extension)) {
    return `Unsupported file extension '${extension}'.`;
  }
  if (file.type && !ALLOWED_UPLOAD_MIME_TYPES.has(file.type.toLowerCase())) {
    return `Unsupported file media type '${file.type}'.`;
  }
  if (file.size <= 0) {
    return "Uploaded file is empty.";
  }
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    return `File exceeds max size of ${MAX_UPLOAD_SIZE_MB} MB.`;
  }
  return null;
}

function statusClass(status) {
  switch (status) {
    case "processing":
      return "status-processing";
    case "processed":
      return "status-processed";
    case "error":
      return "status-error";
    case "created":
    case "uploaded":
    default:
      return "status-created";
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeStringList(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderStringList(container, items, emptyLabel) {
  container.innerHTML = "";
  const values = normalizeStringList(items);
  if (!values.length) {
    container.classList.add("empty");
    const li = document.createElement("li");
    li.textContent = emptyLabel;
    container.appendChild(li);
    return;
  }

  container.classList.remove("empty");
  for (const value of values) {
    const li = document.createElement("li");
    li.textContent = value;
    container.appendChild(li);
  }
}

function normalizeActionItems(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      task: typeof item.task === "string" ? item.task.trim() : "",
      owner: typeof item.owner === "string" ? item.owner.trim() : "",
      dueDate: typeof item.due_date === "string" ? item.due_date.trim() : "",
    }))
    .filter((item) => item.task);
}

function normalizeTranscriptSegments(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => item && typeof item === "object")
    .map((item) => {
      const start = Number(item.start_seconds);
      const end = Number(item.end_seconds);
      const text = typeof item.text === "string" ? item.text.trim() : "";
      const speaker = typeof item.speaker === "string" && item.speaker.trim()
        ? item.speaker.trim()
        : "Speaker 1";
      return {
        startSeconds: Number.isFinite(start) ? Math.max(0, start) : 0,
        endSeconds: Number.isFinite(end) ? Math.max(0, end) : 0,
        text,
        speaker,
      };
    })
    .filter((item) => item.text);
}

function formatSeconds(totalSeconds) {
  const safeSeconds = Number.isFinite(totalSeconds) ? Math.max(0, Math.floor(totalSeconds)) : 0;
  const mins = Math.floor(safeSeconds / 60);
  const secs = safeSeconds % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function renderActionItemsTable(tableEl, items, emptyLabel) {
  const tbody = tableEl.querySelector("tbody");
  tbody.innerHTML = "";

  const normalized = normalizeActionItems(items);
  if (!normalized.length) {
    const tr = document.createElement("tr");
    tr.className = "empty";
    tr.innerHTML = `<td colspan="3">${escapeHtml(emptyLabel)}</td>`;
    tbody.appendChild(tr);
    return;
  }

  for (const item of normalized) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.task)}</td>
      <td>${escapeHtml(item.owner || "Unassigned")}</td>
      <td>${escapeHtml(item.dueDate || "Not set")}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderTimelineList(listEl, speakerSelectEl, segments, speakerFilter, textQuery, onJump) {
  const normalized = normalizeTranscriptSegments(segments);
  const speakers = [...new Set(normalized.map((segment) => segment.speaker))].sort((a, b) =>
    a.localeCompare(b),
  );

  const previousValue = speakerSelectEl.value;
  speakerSelectEl.innerHTML = '<option value="">All speakers</option>';
  for (const speaker of speakers) {
    const option = document.createElement("option");
    option.value = speaker;
    option.textContent = speaker;
    speakerSelectEl.appendChild(option);
  }

  const preferredFilter = speakerFilter || previousValue;
  if (preferredFilter && speakers.includes(preferredFilter)) {
    speakerSelectEl.value = preferredFilter;
  } else {
    speakerSelectEl.value = "";
  }

  const query = textQuery.trim().toLowerCase();
  const activeSpeaker = speakerSelectEl.value;
  const filtered = normalized.filter((segment) => {
    if (activeSpeaker && segment.speaker !== activeSpeaker) return false;
    if (query && !segment.text.toLowerCase().includes(query)) return false;
    return true;
  });

  listEl.innerHTML = "";
  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "timeline-empty";
    empty.textContent = "No timeline segments match the current filters.";
    listEl.appendChild(empty);
    return activeSpeaker;
  }

  for (const segment of filtered) {
    const row = document.createElement("div");
    row.className = "timeline-item";

    const info = document.createElement("div");
    info.innerHTML = `
      <p class="timeline-meta">
        <span class="timeline-time">${escapeHtml(formatSeconds(segment.startSeconds))} - ${escapeHtml(formatSeconds(segment.endSeconds))}</span>
        <span class="timeline-speaker">${escapeHtml(segment.speaker)}</span>
      </p>
      <p class="timeline-text">${escapeHtml(segment.text)}</p>
    `;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost jump-btn";
    button.textContent = "Find in transcript";
    button.addEventListener("click", () => onJump(segment));

    row.append(info, button);
    listEl.appendChild(row);
  }

  return activeSpeaker;
}

function renderTranscriptWithHighlights(element, transcriptText, query, matchCountEl) {
  const text = transcriptText || "No transcript yet.";
  const term = query.trim();

  if (!term) {
    element.textContent = text;
    matchCountEl.textContent = "";
    return;
  }

  const regex = new RegExp(`(${escapeRegExp(term)})`, "ig");
  const parts = text.split(regex);
  let matches = 0;
  const html = parts
    .map((part, idx) => {
      if (idx % 2 === 1) {
        matches += 1;
        return `<mark>${escapeHtml(part)}</mark>`;
      }
      return escapeHtml(part);
    })
    .join("");
  element.innerHTML = html;
  matchCountEl.textContent = matches === 1 ? "1 match" : `${matches} matches`;
}

function renderStatusTrack(trackEl, noteEl, status) {
  const statusToIndex = {
    created: 0,
    uploaded: 1,
    processing: 2,
    processed: 3,
    error: 2,
  };
  const statusToNote = {
    created: "Meeting created. Upload audio to continue.",
    uploaded: "Audio uploaded. Start processing when ready.",
    processing: "Processing is running. The UI auto-refreshes status.",
    processed: "Processing complete. Review insights and transcript.",
    error: "Processing failed. Check the error message and retry after fixing the issue.",
  };

  const currentIndex = statusToIndex[status] ?? 0;
  const steps = Array.from(trackEl.querySelectorAll("li"));
  trackEl.classList.toggle("has-error", status === "error");

  for (const [index, step] of steps.entries()) {
    step.classList.remove("done", "current");
    if (index < currentIndex) {
      step.classList.add("done");
    } else if (index === currentIndex) {
      step.classList.add("current");
    }
  }

  if (status === "processed") {
    for (const step of steps) {
      step.classList.add("done");
    }
    steps[steps.length - 1]?.classList.add("current");
  }

  noteEl.textContent = statusToNote[status] || "Track meeting progress through upload and processing.";
}

function renderAuth() {
  els.userChip.textContent = state.user ? `Signed in as ${state.user.email}` : "Signed out";
  const disabled = state.busy;
  els.registerBtn.disabled = disabled;
  els.loginBtn.disabled = disabled;
  els.logoutBtn.disabled = disabled || !state.token;
  els.refreshBtn.disabled = disabled || !state.token;
  els.meetingTitleInput.disabled = disabled || !state.token;
  els.createMeetingForm.querySelector("button[type='submit']").disabled = disabled || !state.token;
}

function getSelectedMeeting() {
  return state.meetings.find((m) => m.id === state.selectedMeetingId) || null;
}

function clearProcessingPoll() {
  if (processingPoll.timerId != null) {
    window.clearInterval(processingPoll.timerId);
  }
  processingPoll.timerId = null;
  processingPoll.inFlight = false;
  processingPoll.meetingId = null;
}

async function pollProcessingMeeting() {
  if (processingPoll.inFlight || state.busy) return;
  if (!state.token || processingPoll.meetingId == null) {
    clearProcessingPoll();
    return;
  }

  processingPoll.inFlight = true;
  const polledMeetingId = processingPoll.meetingId;

  try {
    await loadMeetings(polledMeetingId);
    render();

    const meeting = getSelectedMeeting();
    if (!meeting || meeting.id !== polledMeetingId) {
      clearProcessingPoll();
      return;
    }

    if (meeting.status !== "processing") {
      if (meeting.status === "processed") {
        log(`Meeting #${meeting.id} finished processing.`);
      } else if (meeting.status === "error") {
        log(
          `Meeting #${meeting.id} processing failed: ${meeting.error_message || "Unknown error"}`,
          "error",
        );
      } else {
        log(`Meeting #${meeting.id} status changed to ${meeting.status}.`);
      }
      clearProcessingPoll();
    }
  } catch (error) {
    clearProcessingPoll();
    log(`Status polling stopped: ${error.message || String(error)}`, "error");
  } finally {
    processingPoll.inFlight = false;
  }
}

function syncProcessingPoll() {
  const meeting = getSelectedMeeting();
  if (!state.token || !meeting || meeting.status !== "processing") {
    if (processingPoll.timerId != null) {
      clearProcessingPoll();
    }
    return;
  }

  if (processingPoll.timerId != null && processingPoll.meetingId === meeting.id) {
    return;
  }

  clearProcessingPoll();
  processingPoll.meetingId = meeting.id;
  processingPoll.timerId = window.setInterval(() => {
    void pollProcessingMeeting();
  }, 2500);
  log(`Polling status for meeting #${meeting.id}...`);
}

function renderMeetingList() {
  if (!state.token) {
    els.meetingList.innerHTML = '<li class="details empty">Log in to load meetings.</li>';
    return;
  }

  if (!state.meetings.length) {
    els.meetingList.innerHTML = '<li class="details empty">No meetings yet. Create one to start.</li>';
    return;
  }

  els.meetingList.innerHTML = "";
  for (const meeting of state.meetings) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `meeting-item${meeting.id === state.selectedMeetingId ? " active" : ""}`;
    btn.dataset.meetingId = String(meeting.id);
    btn.innerHTML = `
      <span class="title">${escapeHtml(meeting.title)}</span>
      <span class="status-pill ${statusClass(meeting.status)}">${escapeHtml(meeting.status)}</span>
      <span class="meta">${escapeHtml(formatDate(meeting.created_at))}</span>
    `;
    btn.addEventListener("click", () => {
      state.selectedMeetingId = meeting.id;
      render();
    });
    li.appendChild(btn);
    els.meetingList.appendChild(li);
  }
}

function renderMeetingDetails() {
  const meeting = getSelectedMeeting();
  if (!meeting) {
    els.meetingDetails.className = "details empty";
    els.meetingDetails.textContent = state.token
      ? "Select a meeting to view details."
      : "Log in to view meeting details.";
    return;
  }

  const fragment = els.meetingDetailsTemplate.content.cloneNode(true);
  const root = fragment.querySelector(".details-panel");
  const statusTrack = root.querySelector("[data-field='status_track']");
  const statusNote = root.querySelector("[data-field='status_note']");
  renderStatusTrack(statusTrack, statusNote, meeting.status);

  root.querySelector("[data-field='id']").textContent = String(meeting.id);
  root.querySelector("[data-field='status']").innerHTML = `<span class="status-pill ${statusClass(meeting.status)}">${escapeHtml(meeting.status)}</span>`;
  root.querySelector("[data-field='created_at']").textContent = formatDate(meeting.created_at, "Not available");
  root.querySelector("[data-field='processing_started_at']").textContent = formatDate(meeting.processing_started_at, "Not started");
  root.querySelector("[data-field='processed_at']").textContent = formatDate(meeting.processed_at, "Not processed");
  root.querySelector("[data-field='processing_task_id']").textContent = meeting.processing_task_id || "Not queued";
  root.querySelector("[data-field='original_filename']").textContent = meeting.original_filename || "No file uploaded";
  root.querySelector("[data-field='file_size_bytes']").textContent = formatBytes(meeting.file_size_bytes);
  root.querySelector("[data-field='summary']").textContent = meeting.summary || "No summary yet. Process the meeting to generate one.";
  renderStringList(root.querySelector("[data-field='key_points']"), meeting.key_points, "No key points yet.");
  renderStringList(root.querySelector("[data-field='decisions']"), meeting.decisions, "No decisions yet.");
  renderActionItemsTable(
    root.querySelector("[data-field='action_items_table']"),
    meeting.action_items,
    "No action items detected for this meeting.",
  );
  renderStringList(root.querySelector("[data-field='risks']"), meeting.risks, "No risks noted.");
  root.querySelector("[data-field='raw_json']").textContent = JSON.stringify(meeting, null, 2);

  const errorEl = root.querySelector("[data-field='error_message']");
  if (meeting.error_message) {
    errorEl.textContent = meeting.error_message;
    errorEl.classList.add("show");
  } else {
    errorEl.textContent = "";
    errorEl.classList.remove("show");
  }

  const uploadForm = root.querySelector("[data-role='upload-form']");
  const processBtn = root.querySelector("[data-role='process-btn']");
  const downloadBtn = root.querySelector("[data-role='download-btn']");
  const fileInput = uploadForm.querySelector("input[type='file']");
  const uploadHint = root.querySelector("[data-field='upload_hint']");
  const transcriptInput = root.querySelector("[data-role='transcript-search']");
  const transcriptEl = root.querySelector("[data-field='transcript']");
  const transcriptMatchCountEl = root.querySelector("[data-field='transcript_match_count']");
  const speakerFilterEl = root.querySelector("[data-role='speaker-filter']");
  const timelineListEl = root.querySelector("[data-field='timeline_list']");
  const tabButtons = Array.from(root.querySelectorAll("[data-role='tab-btn']"));
  const tabPanels = Array.from(root.querySelectorAll("[data-role='tab-panel']"));

  if (!meeting.audio_path) {
    uploadHint.textContent = "No audio uploaded yet. Upload an audio file before processing.";
  } else {
    uploadHint.textContent = `Current audio: ${meeting.original_filename || "Uploaded file"}`;
  }

  const transcriptText = meeting.transcript || "No transcript yet.";
  const timelineSegments = meeting.transcript_segments || [];

  const rerenderTranscriptViews = () => {
    renderTranscriptWithHighlights(
      transcriptEl,
      transcriptText,
      state.transcriptQuery,
      transcriptMatchCountEl,
    );
    const selectedSpeaker = renderTimelineList(
      timelineListEl,
      speakerFilterEl,
      timelineSegments,
      state.timelineSpeaker,
      state.transcriptQuery,
      (segment) => {
        state.transcriptQuery = segment.text;
        transcriptInput.value = state.transcriptQuery;
        rerenderTranscriptViews();
        state.detailsTab = "transcript";
        const mark = transcriptEl.querySelector("mark");
        if (mark) {
          mark.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      },
    );
    state.timelineSpeaker = selectedSpeaker || "";
  };

  transcriptInput.value = state.transcriptQuery;
  speakerFilterEl.value = state.timelineSpeaker;
  rerenderTranscriptViews();

  transcriptInput.addEventListener("input", () => {
    state.transcriptQuery = transcriptInput.value;
    rerenderTranscriptViews();
  });

  speakerFilterEl.addEventListener("change", () => {
    state.timelineSpeaker = speakerFilterEl.value;
    rerenderTranscriptViews();
  });

  const availableTabs = new Set(tabButtons.map((button) => button.dataset.tab));
  if (!availableTabs.has(state.detailsTab)) {
    state.detailsTab = "overview";
  }

  const setActiveTab = (tabName) => {
    state.detailsTab = tabName;
    for (const button of tabButtons) {
      const isActive = button.dataset.tab === tabName;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-selected", isActive ? "true" : "false");
    }
    for (const panel of tabPanels) {
      panel.hidden = panel.dataset.tabPanel !== tabName;
    }
  };

  for (const button of tabButtons) {
    button.addEventListener("click", () => {
      setActiveTab(button.dataset.tab || "overview");
    });
  }

  setActiveTab(state.detailsTab);

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!fileInput.files || !fileInput.files.length) {
      log("Select an audio file before uploading.", "error");
      return;
    }
    const selectedFile = fileInput.files[0];
    const validationError = validateUploadCandidate(selectedFile);
    if (validationError) {
      log(validationError, "error");
      return;
    }
    await withBusy(async () => {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const result = await apiRequest(`/meetings/${meeting.id}/upload`, {
        method: "POST",
        body: formData,
      });
      log(`Uploaded ${result.filename} for meeting #${meeting.id}.`);
      await reloadMeetings(meeting.id);
      fileInput.value = "";
    });
  });

  processBtn.disabled = state.busy || meeting.status === "processing" || !meeting.audio_path;
  if (!meeting.audio_path) {
    processBtn.textContent = "Upload audio first";
  } else if (meeting.status === "processing") {
    processBtn.textContent = "Processing...";
  } else if (meeting.status === "processed") {
    processBtn.textContent = "Reprocess Meeting";
  } else {
    processBtn.textContent = "Process Meeting";
  }
  processBtn.addEventListener("click", async () => {
    await withBusy(async () => {
      const result = await apiRequest(`/meetings/${meeting.id}/process`, { method: "POST" });
      log(result.message || `Started processing meeting #${meeting.id}.`);
      await reloadMeetings(meeting.id);
    });
  });

  downloadBtn.disabled = state.busy || !meeting.audio_path;
  downloadBtn.addEventListener("click", async () => {
    await withBusy(async () => {
      const headers = new Headers();
      headers.set("Authorization", `Bearer ${state.token}`);
      const response = await fetch(`/meetings/${meeting.id}/download`, { headers });
      if (response.status === 401) {
        resetSession();
        throw new Error(SESSION_EXPIRED_MESSAGE);
      }
      if (!response.ok) {
        const contentType = response.headers.get("content-type") || "";
        let detail = `HTTP ${response.status}`;
        if (contentType.includes("application/json")) {
          const payload = await response.json();
          detail = payload.detail || detail;
        }
        throw new Error(detail);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = meeting.original_filename || `meeting-${meeting.id}.bin`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      log(`Downloaded audio for meeting #${meeting.id}.`);
    });
  });

  els.meetingDetails.className = "details";
  els.meetingDetails.innerHTML = "";
  els.meetingDetails.appendChild(fragment);
}

function render() {
  renderAuth();
  renderMeetingList();
  renderMeetingDetails();
  syncProcessingPoll();
}

async function withBusy(fn) {
  if (state.busy) return;
  state.busy = true;
  renderAuth();
  try {
    await fn();
  } catch (error) {
    log(error.message || String(error), "error");
  } finally {
    state.busy = false;
    render();
  }
}

async function loadCurrentUser() {
  if (!state.token) {
    state.user = null;
    return null;
  }
  const user = await apiRequest("/me");
  state.user = user;
  return user;
}

async function loadMeetings(preferredId = null) {
  if (!state.token) {
    state.meetings = [];
    state.selectedMeetingId = null;
    return;
  }
  const meetings = await apiRequest("/meetings");
  state.meetings = meetings;
  if (preferredId != null && meetings.some((m) => m.id === preferredId)) {
    state.selectedMeetingId = preferredId;
    return;
  }
  if (!meetings.some((m) => m.id === state.selectedMeetingId)) {
    state.selectedMeetingId = meetings[0]?.id ?? null;
  }
}

async function reloadMeetings(preferredId = state.selectedMeetingId) {
  await loadMeetings(preferredId);
  render();
}

async function initialize() {
  render();
  if (!state.token) return;

  await withBusy(async () => {
    try {
      await loadCurrentUser();
      await loadMeetings();
      log("Restored session from local storage.");
    } catch (error) {
      resetSession();
      log(`Session restore failed: ${error.message || String(error)}`, "error");
    }
  });
}

async function handleRegister() {
  const email = els.emailInput.value.trim();
  const password = els.passwordInput.value;
  if (!email || !password) {
    log("Email and password are required.", "error");
    return;
  }

  await withBusy(async () => {
    await apiRequest("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    log(`Registered ${email}.`);
  });
}

async function handleLogin() {
  const email = els.emailInput.value.trim();
  const password = els.passwordInput.value;
  if (!email || !password) {
    log("Email and password are required.", "error");
    return;
  }

  await withBusy(async () => {
    const tokenResponse = await apiRequest("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setToken(tokenResponse.access_token);
    await loadCurrentUser();
    await loadMeetings();
    log(`Logged in as ${email}.`);
  });
}

async function handleLogout() {
  resetSession();
  log("Logged out.");
}

async function handleCreateMeeting(event) {
  event.preventDefault();
  const title = els.meetingTitleInput.value.trim();
  if (!title) {
    log("Meeting title is required.", "error");
    return;
  }
  if (!state.token) {
    log("Log in before creating meetings.", "error");
    return;
  }

  await withBusy(async () => {
    const meeting = await apiRequest("/meetings", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
    els.meetingTitleInput.value = "";
    log(`Created meeting #${meeting.id}: ${meeting.title}`);
    await reloadMeetings(meeting.id);
  });
}

async function handleRefresh() {
  if (!state.token) {
    log("Log in before refreshing meetings.", "error");
    return;
  }
  await withBusy(async () => {
    await loadCurrentUser();
    await loadMeetings();
    log("Meeting list refreshed.");
  });
}

els.registerBtn.addEventListener("click", handleRegister);
els.loginBtn.addEventListener("click", handleLogin);
els.logoutBtn.addEventListener("click", handleLogout);
els.refreshBtn.addEventListener("click", () => {
  void handleRefresh();
});
els.createMeetingForm.addEventListener("submit", (event) => {
  void handleCreateMeeting(event);
});

initialize();
