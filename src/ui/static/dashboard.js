/**
 * ExamForge AI Studio — Admin Frontend Dashboard Logic.
 */

// State
let authToken = localStorage.getItem("ef_token") || "";
let activeSubjects = [];
let currentConfig = {};
let currentModalPayload = null;

// DOM Elements
const loginOverlay = document.getElementById("login-overlay");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const btnLogout = document.getElementById("btn-logout");

// Worker Top Controls
const workerBadge = document.getElementById("worker-badge");
const workerStatusText = document.getElementById("worker-status-text");
const btnStart = document.getElementById("btn-start");
const btnPause = document.getElementById("btn-pause");
const btnStop = document.getElementById("btn-stop");

// Tabs
const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanes = document.querySelectorAll(".tab-pane");

// Matrix Tab
const subjectsGrid = document.getElementById("subjects-grid");
const btnRefreshSubjects = document.getElementById("btn-refresh-subjects");
const metricSubject = document.getElementById("metric-subject");
const metricTopic = document.getElementById("metric-topic");
const metricAction = document.getElementById("metric-action");
const logList = document.getElementById("log-list");

// Webhook Settings Tab
const envProd = document.getElementById("env-prod");
const envLocal = document.getElementById("env-local");
const cfgEndpointUrl = document.getElementById("cfg-endpoint-url");
const cfgApiKey = document.getElementById("cfg-api-key");
const cfgBatchSize = document.getElementById("cfg-batch-size");
const cfgAutoDispatch = document.getElementById("cfg-auto-dispatch");
const cfgGeminiKey = document.getElementById("cfg-gemini-key");
const cfgOpenrouterKey = document.getElementById("cfg-openrouter-key");
const cfgGroqKey = document.getElementById("cfg-groq-key");
const cfgTavilyKey = document.getElementById("cfg-tavily-key");
const cfgBraveKey = document.getElementById("cfg-brave-key");
const cfgExaKey = document.getElementById("cfg-exa-key");
const cfgSearchEnabled = document.getElementById("cfg-search-enabled");
const btnTestWebhook = document.getElementById("btn-test-webhook");
const testWebhookResult = document.getElementById("test-webhook-result");
const btnSaveConfig = document.getElementById("btn-save-config");

// Dispatches Tab
const dispatchesTbody = document.getElementById("dispatches-tbody");
const btnRefreshDispatches = document.getElementById("btn-refresh-dispatches");

// Syllabus Tab
const sylSubjectSelect = document.getElementById("syl-subject-select");
const sylNewSubject = document.getElementById("syl-new-subject");
const sylExamCode = document.getElementById("syl-exam-code");
const sylFileInput = document.getElementById("syl-file-input");
const sylTextInput = document.getElementById("syl-text-input");
const btnParseSyllabus = document.getElementById("btn-parse-syllabus");
const treeContainer = document.getElementById("tree-container");
const btnSaveTree = document.getElementById("btn-save-tree");

// Modal
const jsonModal = document.getElementById("json-modal");
const modalTitle = document.getElementById("modal-title");
const modalCode = document.getElementById("modal-code");
const btnCloseModal = document.getElementById("btn-close-modal");
const btnModalDismiss = document.getElementById("btn-modal-dismiss");
const btnDownloadJson = document.getElementById("btn-download-json");


// ================= HELPER FETCH WRAPPER =================
async function apiFetch(url, options = {}) {
  options.headers = options.headers || {};
  if (authToken) {
    options.headers["Authorization"] = `Bearer ${authToken}`;
  }
  options.headers["Content-Type"] = options.headers["Content-Type"] || "application/json";

  const res = await fetch(url, options);
  if (res.status === 401) {
    showLogin();
    throw new Error("Session expired or unauthorized");
  }
  return res;
}

// ================= AUTHENTICATION =================
function showLogin() {
  authToken = "";
  localStorage.removeItem("ef_token");
  const emailInput = document.getElementById("admin-email");
  const passInput = document.getElementById("admin-password");
  if (emailInput) emailInput.value = "";
  if (passInput) passInput.value = "";
  loginOverlay.classList.remove("hidden");
}

function hideLogin() {
  loginOverlay.classList.add("hidden");
}

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.classList.add("hidden");

  const email = document.getElementById("admin-email").value.trim();
  const password = document.getElementById("admin-password").value.trim();

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Authentication failed.");
    }

    const data = await res.json();
    authToken = data.access_token;
    localStorage.setItem("ef_token", authToken);
    hideLogin();
    initApp();
  } catch (err) {
    loginError.textContent = err.message;
    loginError.classList.remove("hidden");
  }
});

btnLogout.addEventListener("click", async () => {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } catch (e) {}
  showLogin();
});

// Check existing session
async function checkAuth() {
  if (!authToken) {
    showLogin();
    return;
  }
  try {
    const res = await apiFetch("/api/auth/me");
    if (res.ok) {
      hideLogin();
      initApp();
    } else {
      showLogin();
    }
  } catch (e) {
    showLogin();
  }
}

// ================= TAB NAVIGATION =================
tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("active"));
    tabPanes.forEach((p) => p.classList.remove("active"));

    btn.classList.add("active");
    const target = btn.getAttribute("data-tab");
    const pane = document.getElementById(target);
    if (pane) pane.classList.add("active");

    if (target === "tab-matrix") loadSubjects();
    if (target === "tab-dispatches") loadDispatches();
    if (target === "tab-webhook") loadConfig();
    if (target === "tab-syllabus") loadSyllabusTab();
  });
});

// ================= WORKER CONTROLS =================
btnStart.addEventListener("click", async () => {
  await apiFetch("/api/worker/start", { method: "POST" });
  pollWorker();
});

btnPause.addEventListener("click", async () => {
  await apiFetch("/api/worker/pause", { method: "POST" });
  pollWorker();
});

btnStop.addEventListener("click", async () => {
  await apiFetch("/api/worker/stop", { method: "POST" });
  pollWorker();
});

async function pollWorker() {
  try {
    const res = await apiFetch("/api/worker/status");
    if (!res.ok) return;
    const data = await res.json();

    // Update Top Badge
    workerBadge.className = "worker-status-badge";
    if (data.is_running && !data.is_paused) {
      workerBadge.classList.add("running");
      workerStatusText.textContent = "Worker: Running";
    } else if (data.is_paused) {
      workerBadge.classList.add("paused");
      workerStatusText.textContent = "Worker: Paused";
    } else {
      workerStatusText.textContent = "Worker: Idle";
    }

    // Update Live Metrics
    metricSubject.textContent = data.current_subject || "—";
    metricTopic.textContent = data.current_topic || "—";
    metricAction.textContent = data.last_action || "Idle";

    // Update Logs
    if (data.recent_logs && data.recent_logs.length > 0) {
      logList.innerHTML = data.recent_logs
        .map((l) => `<div class="log-entry ${l.level || 'info'}"><span class="log-time">[${l.timestamp}]</span> ${l.message}</div>`)
        .join("");
      logList.scrollTop = logList.scrollHeight;
    }
  } catch (e) {}
}

// ================= SCREEN A: SUBJECT MATRIX =================
async function loadSubjects() {
  try {
    const res = await apiFetch("/api/subjects");
    if (!res.ok) return;
    activeSubjects = await res.json();

    subjectsGrid.innerHTML = "";
    if (activeSubjects.length === 0) {
      subjectsGrid.innerHTML = `<div class="empty-state">No subjects found.</div>`;
      return;
    }

    activeSubjects.forEach((s) => {
      const ready = s.ready_count || 0;
      const batchGoal = currentConfig.batch_size || 100;
      const progressPercent = Math.min(100, Math.round((ready / batchGoal) * 100));
      const remaining = Math.max(0, batchGoal - ready);

      const card = document.createElement("div");
      card.className = `glass-panel subject-card ${s.is_active ? "active" : "paused"}`;
      card.innerHTML = `
        <div class="card-top">
          <div class="card-title-group">
            <h3>${s.name}</h3>
            <span class="badge-exam">${s.exam_code || "RRB"}</span>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" ${s.is_active ? "checked" : ""} data-subject="${s.name}">
            <span class="slider"></span>
          </label>
        </div>

        <div class="progress-block">
          <div class="progress-labels">
            <span>Ready: <strong style="color: var(--accent-cyan);">${ready}</strong> / ${batchGoal} Qs</span>
            <span style="font-size: 11px; color: ${remaining === 0 ? 'var(--accent-green)' : 'var(--text-muted)'};">
              ${remaining === 0 ? '✓ Ready to send' : `${remaining} to dispatch`}
            </span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-bar-fill" style="width: ${progressPercent}%;"></div>
          </div>
        </div>

        <div class="card-bottom">
          <div class="speed-control">
            <span>Delay: <strong id="spd-val-${s.name}">${s.speed_delay_seconds || 15}s</strong></span>
            <input type="range" min="5" max="60" value="${s.speed_delay_seconds || 15}" data-speed-subject="${s.name}">
          </div>
          <div style="margin-top: 10px; display: flex; justify-content: flex-end;">
            <button class="btn btn-sm btn-secondary" onclick="manualSend('${s.name}')" ${ready === 0 ? 'disabled' : ''}>
              ⚡ Dispatch Now (${ready})
            </button>
          </div>
        </div>
      `;

      // Toggle Listener
      const toggle = card.querySelector("input[type='checkbox']");
      toggle.addEventListener("change", async (e) => {
        const isActive = e.target.checked;
        await apiFetch(`/api/subjects/${encodeURIComponent(s.name)}/toggle`, {
          method: "POST",
          body: JSON.stringify({ is_active: isActive }),
        });
        loadSubjects();
      });

      // Speed Slider Listener
      const slider = card.querySelector("input[type='range']");
      const spdVal = card.querySelector(`#spd-val-${s.name}`);
      slider.addEventListener("input", (e) => {
        spdVal.textContent = `${e.target.value}s`;
      });
      slider.addEventListener("change", async (e) => {
        await apiFetch(`/api/subjects/${encodeURIComponent(s.name)}/speed`, {
          method: "POST",
          body: JSON.stringify({ speed_seconds: parseInt(e.target.value) }),
        });
      });

      subjectsGrid.appendChild(card);
    });
  } catch (e) {
    console.error("Failed to load subjects:", e);
  }
}

btnRefreshSubjects.addEventListener("click", loadSubjects);

window.manualSend = async function (subjectName) {
  if (!confirm(`Force dispatch pending questions for ${subjectName} to ExamForge right now?`)) return;
  try {
    const res = await apiFetch(`/api/dispatches/manual?subject_name=${encodeURIComponent(subjectName)}&count=100`, {
      method: "POST",
    });
    const data = await res.json();
    if (res.ok) {
      alert(`Success! Dispatched ${data.dispatched_count} questions (Batch: ${data.batch_number}).`);
      loadSubjects();
    } else {
      alert(`Dispatch failed: ${data.detail || JSON.stringify(data)}`);
    }
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
};

// ================= SCREEN B: WEBHOOK & SETTINGS =================
async function loadConfig() {
  try {
    const res = await apiFetch("/api/config");
    if (!res.ok) return;
    currentConfig = await res.json();

    cfgEndpointUrl.value = currentConfig.examforge_url || "";
    cfgApiKey.value = currentConfig.examforge_api_key || "";
    cfgBatchSize.value = currentConfig.batch_size || 100;
    cfgAutoDispatch.value = String(currentConfig.auto_dispatch !== false);

    cfgGeminiKey.value = currentConfig.gemini_api_key || "";
    cfgOpenrouterKey.value = currentConfig.openrouter_api_key || "";
    cfgGroqKey.value = currentConfig.groq_api_key || "";
    if (cfgTavilyKey) cfgTavilyKey.value = currentConfig.tavily_api_key || "";
    if (cfgBraveKey) cfgBraveKey.value = currentConfig.brave_api_key || "";
    if (cfgExaKey) cfgExaKey.value = currentConfig.exa_api_key || "";
    cfgSearchEnabled.checked = currentConfig.web_search_enabled !== false;

    // Radio
    if (cfgEndpointUrl.value.includes("localhost")) {
      envLocal.checked = true;
    } else {
      envProd.checked = true;
    }
  } catch (e) {}
}

envProd.addEventListener("change", () => {
  if (envProd.checked) {
    cfgEndpointUrl.value = "https://examforge-pink.vercel.app/api/questions/ai-ingest";
  }
});

envLocal.addEventListener("change", () => {
  if (envLocal.checked) {
    cfgEndpointUrl.value = "http://localhost:3000/api/questions/ai-ingest";
  }
});

btnTestWebhook.addEventListener("click", async () => {
  testWebhookResult.textContent = "Testing endpoint connection...";
  testWebhookResult.style.color = "var(--accent-cyan)";

  try {
    const res = await apiFetch("/api/config/test-webhook", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      testWebhookResult.textContent = `✓ ${data.message}`;
      testWebhookResult.style.color = "var(--accent-green)";
    } else {
      testWebhookResult.textContent = `✗ ${data.message}`;
      testWebhookResult.style.color = "var(--accent-red)";
    }
  } catch (e) {
    testWebhookResult.textContent = `✗ Error: ${e.message}`;
    testWebhookResult.style.color = "var(--accent-red)";
  }
});

btnSaveConfig.addEventListener("click", async () => {
  const payload = {
    examforge_url: cfgEndpointUrl.value.trim(),
    examforge_api_key: cfgApiKey.value.trim(),
    batch_size: parseInt(cfgBatchSize.value) || 100,
    auto_dispatch: cfgAutoDispatch.value === "true",
    gemini_api_key: cfgGeminiKey.value.trim(),
    openrouter_api_key: cfgOpenrouterKey.value.trim(),
    groq_api_key: cfgGroqKey.value.trim(),
    tavily_api_key: cfgTavilyKey ? cfgTavilyKey.value.trim() : "",
    brave_api_key: cfgBraveKey ? cfgBraveKey.value.trim() : "",
    exa_api_key: cfgExaKey ? cfgExaKey.value.trim() : "",
    web_search_enabled: cfgSearchEnabled.checked,
  };

  try {
    const res = await apiFetch("/api/config", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      alert("Configuration saved successfully!");
      loadConfig();
    } else {
      alert("Failed to save configuration.");
    }
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
});

// ================= SCREEN C: DISPATCH LOGS =================
async function loadDispatches() {
  try {
    const res = await apiFetch("/api/dispatches?limit=50");
    if (!res.ok) return;
    const dispatches = await res.json();

    dispatchesTbody.innerHTML = "";
    if (dispatches.length === 0) {
      dispatchesTbody.innerHTML = `<tr><td colspan="7" class="text-center">No batches have been dispatched yet.</td></tr>`;
      return;
    }

    dispatches.forEach((d) => {
      const isOk = d.status_code >= 200 && d.status_code < 300;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong style="font-family: var(--font-mono); color: var(--accent-cyan);">${d.batch_number}</strong></td>
        <td>${d.exam_code} - ${d.subject_name}</td>
        <td>${d.topic_name || "General"}</td>
        <td><strong>${d.question_count}</strong> Qs</td>
        <td><span class="status-tag ${isOk ? 'ok' : 'fail'}">${d.status_code || 'Err'}</span></td>
        <td style="font-size: 11px; color: var(--text-muted);">${d.created_at ? d.created_at.replace('T', ' ').slice(0, 19) : '—'}</td>
        <td>
          <button class="btn btn-sm btn-ghost" onclick="viewBatchJson('${encodeURIComponent(JSON.stringify(d))}')">
            🔍 View JSON
          </button>
        </td>
      `;
      dispatchesTbody.appendChild(tr);
    });
  } catch (e) {}
}

btnRefreshDispatches.addEventListener("click", loadDispatches);

window.viewBatchJson = function (encodedStr) {
  try {
    const batch = JSON.parse(decodeURIComponent(encodedStr));
    currentModalPayload = {
      examCode: batch.exam_code,
      subjectName: batch.subject_name,
      topicName: batch.topic_name,
      questions: batch.questions_payload || [],
    };

    modalTitle.textContent = `Batch: ${batch.batch_number} (${batch.question_count} Questions)`;
    modalCode.textContent = JSON.stringify(currentModalPayload, null, 2);
    jsonModal.classList.remove("hidden");
  } catch (e) {
    alert("Error parsing payload");
  }
};

btnCloseModal.addEventListener("click", () => jsonModal.classList.add("hidden"));
btnModalDismiss.addEventListener("click", () => jsonModal.classList.add("hidden"));

btnDownloadJson.addEventListener("click", () => {
  if (!currentModalPayload) return;
  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentModalPayload, null, 2));
  const a = document.createElement("a");
  a.setAttribute("href", dataStr);
  a.setAttribute("download", `examforge_batch_${Date.now()}.json`);
  document.body.appendChild(a);
  a.click();
  a.remove();
});

// ================= SCREEN D: SYLLABUS HUB =================
let currentTopicTree = [];

async function loadSyllabusTab(preselectSubject = null) {
  try {
    const res = await apiFetch("/api/subjects");
    if (!res.ok) return;
    const subjects = await res.json();

    sylSubjectSelect.innerHTML = '<option value="">-- Choose Existing Subject --</option>';
    subjects.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.name;
      opt.textContent = `${s.name} (${s.exam_code || 'RRB'})`;
      if (preselectSubject && s.name.toLowerCase() === preselectSubject.toLowerCase()) {
        opt.selected = true;
      }
      sylSubjectSelect.appendChild(opt);
    });

    if (preselectSubject) {
      sylSubjectSelect.value = preselectSubject;
      if (sylNewSubject) sylNewSubject.value = "";
      loadSelectedSubjectSyllabus();
    } else if (sylSubjectSelect.value) {
      loadSelectedSubjectSyllabus();
    }
  } catch (e) {}
}

async function loadSelectedSubjectSyllabus() {
  const subjectName = sylSubjectSelect.value;
  if (!subjectName) {
    if (!sylNewSubject.value.trim()) {
      treeContainer.innerHTML = `<div class="empty-state">Select an existing subject from dropdown OR type a new subject name on the left to get started.</div>`;
    }
    return;
  }

  try {
    const res = await apiFetch("/api/syllabi");
    if (!res.ok) return;
    const allSyllabi = await res.json();
    const match = allSyllabi.find((s) => s.subject_name.toLowerCase() === subjectName.toLowerCase());

    if (match && match.parsed_hierarchy && match.parsed_hierarchy.length > 0) {
      currentTopicTree = match.parsed_hierarchy;
      renderTopicTree(currentTopicTree);
    } else {
      currentTopicTree = [];
      treeContainer.innerHTML = `<div class="empty-state">No parsed topic tree for '${subjectName}'. Paste syllabus text and click "Auto-Parse with AI & Build Tree".</div>`;
    }
  } catch (e) {}
}

// "OR" synchronization: Selecting dropdown clears new subject input
sylSubjectSelect.addEventListener("change", () => {
  if (sylSubjectSelect.value) {
    sylNewSubject.value = "";
  }
  loadSelectedSubjectSyllabus();
});

// "OR" synchronization: Typing new subject resets dropdown selection
sylNewSubject.addEventListener("input", () => {
  const typedName = sylNewSubject.value.trim();
  if (typedName) {
    sylSubjectSelect.value = "";
    currentTopicTree = [];
    treeContainer.innerHTML = `
      <div class="empty-state">
        <div style="font-size: 16px; font-weight: 700; color: var(--accent-cyan); margin-bottom: 6px;">🆕 New Subject: "${typedName}"</div>
        <p style="color: var(--text-secondary); max-width: 380px; margin: 0 auto;">Paste your syllabus text or upload a document on the left, then click <strong>"Auto-Parse with AI & Build Tree"</strong> to extract topics.</p>
      </div>
    `;
  } else {
    loadSelectedSubjectSyllabus();
  }
});

// File Reader
sylFileInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (event) => {
    sylTextInput.value = event.target.result;
  };
  reader.readAsText(file);
});

// Auto-Parse Syllabus (Supports Replace Entire vs Update / Merge)
btnParseSyllabus.addEventListener("click", async () => {
  const newSubj = sylNewSubject.value.trim();
  const existingSubj = sylSubjectSelect.value;
  const targetSubject = newSubj || existingSubj;

  if (!targetSubject) {
    alert("Please select an existing subject from the dropdown OR type a new subject name.");
    sylNewSubject.focus();
    return;
  }

  const examCode = sylExamCode.value.trim() || "RRB";
  const rawText = sylTextInput.value.trim();

  if (!rawText) {
    alert("Please upload a file or paste syllabus text into the text area first.");
    sylTextInput.focus();
    return;
  }

  // Get selected mode (replace vs update)
  const mode = document.querySelector('input[name="syl_mode"]:checked')?.value || "replace";
  const modeLabel = mode === "update" ? "Updating & Merging" : "Parsing & Replacing";

  btnParseSyllabus.disabled = true;
  btnParseSyllabus.textContent = `⏳ ${modeLabel} with AI... Please wait...`;

  try {
    const res = await apiFetch("/api/syllabi/parse", {
      method: "POST",
      body: JSON.stringify({
        subject_name: existingSubj || targetSubject,
        new_subject_name: newSubj || null,
        exam_code: examCode,
        raw_text: rawText,
        mode: mode,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to parse syllabus.");
    }

    const data = await res.json();
    currentTopicTree = data.topics || [];
    renderTopicTree(currentTopicTree);

    // Refresh subjects matrix and syllabus dropdown to include the new/updated subject
    await loadSubjects();
    await loadSyllabusTab(data.subject_name);

    alert(`Success! Syllabus ${mode === 'update' ? 'updated and merged' : 'configured'} for '${data.subject_name}' (${currentTopicTree.length} total topics).`);
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    btnParseSyllabus.disabled = false;
    btnParseSyllabus.textContent = "✨ Auto-Parse with AI & Build Tree";
  }
});

function renderTopicTree(topics) {
  treeContainer.innerHTML = "";
  if (!topics || topics.length === 0) {
    treeContainer.innerHTML = `<div class="empty-state">No topics found.</div>`;
    return;
  }

  topics.forEach((t, idx) => {
    const topicItem = document.createElement("div");
    topicItem.className = "topic-item";

    const conceptsStr = (t.concepts || [])
      .map((c) => (typeof c === "object" ? c.name : c))
      .filter(Boolean)
      .join(", ");

    topicItem.innerHTML = `
      <div class="topic-row">
        <span class="topic-title">${idx + 1}. ${t.name || "Topic"}</span>
        <div style="display: flex; align-items: center; gap: 10px;">
          <input type="range" min="5" max="50" value="${t.weightage || 20}" data-topic-idx="${idx}">
          <span class="weightage-badge" id="wt-val-${idx}">${t.weightage || 20}%</span>
        </div>
      </div>
      <div class="topic-concepts-list">
        <strong>Concepts:</strong> ${conceptsStr || "General syllabus concepts"}
      </div>
    `;

    const slider = topicItem.querySelector("input[type='range']");
    const badge = topicItem.querySelector(`#wt-val-${idx}`);
    slider.addEventListener("input", (e) => {
      badge.textContent = `${e.target.value}%`;
      currentTopicTree[idx].weightage = parseInt(e.target.value);
    });

    treeContainer.appendChild(topicItem);
  });
}

btnSaveTree.addEventListener("click", async () => {
  const targetSubject = sylNewSubject.value.trim() || sylSubjectSelect.value;
  const examCode = sylExamCode.value.trim() || "RRB";

  if (!targetSubject || currentTopicTree.length === 0) {
    alert("No topic tree to save. Please select a subject and generate/adjust the topic tree first.");
    return;
  }

  try {
    const res = await apiFetch("/api/syllabi/update-tree", {
      method: "POST",
      body: JSON.stringify({
        subject_name: targetSubject,
        exam_code: examCode,
        parsed_hierarchy: currentTopicTree,
      }),
    });

    if (res.ok) {
      alert(`Topic tree blueprint saved successfully for '${targetSubject}'!`);
    } else {
      alert("Failed to save topic tree.");
    }
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
});

// ================= INITIALIZATION =================
function initApp() {
  loadConfig();
  loadSubjects();
  loadSyllabusTab();
  pollWorker();
  setInterval(pollWorker, 3000);
}

// Start Auth Check on Page Load
document.addEventListener("DOMContentLoaded", checkAuth);
