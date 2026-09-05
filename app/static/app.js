const form = document.getElementById("report-form");
const questionInput = document.getElementById("question");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const statusText = document.getElementById("status-text");
const errorEl = document.getElementById("error");
const resultEl = document.getElementById("result");
const reportBody = document.getElementById("report-body");
const revisionBadge = document.getElementById("revision-badge");
const citationsBlock = document.getElementById("citations-block");
const citationsList = document.getElementById("citations-list");
const traceList = document.getElementById("trace-list");
const pipelineSteps = Array.from(document.querySelectorAll(".pipeline-step"));

const PIPELINE_ORDER = ["plan", "research", "analyze", "write", "critique"];
let pipelineTimer = null;

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderReport(text) {
  const escaped = escapeHtml(text || "");
  return escaped.replace(/\[([^\[\]]+)\]/g, '<span class="cite">[$1]</span>');
}

function startPipelineAnimation() {
  let i = 0;
  pipelineSteps.forEach((el) => el.classList.remove("active"));
  pipelineTimer = setInterval(() => {
    pipelineSteps.forEach((el) => el.classList.remove("active"));
    const step = PIPELINE_ORDER[i % PIPELINE_ORDER.length];
    const el = document.querySelector(`.pipeline-step[data-step="${step}"]`);
    if (el) el.classList.add("active");
    i += 1;
  }, 900);
}

function stopPipelineAnimation() {
  if (pipelineTimer) {
    clearInterval(pipelineTimer);
    pipelineTimer = null;
  }
  pipelineSteps.forEach((el) => el.classList.remove("active"));
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? "Running…" : "Run";
  statusEl.hidden = !isLoading;
  if (isLoading) {
    startPipelineAnimation();
  } else {
    stopPipelineAnimation();
  }
}

function showError(message) {
  errorEl.hidden = false;
  errorEl.textContent = message;
}

function clearError() {
  errorEl.hidden = true;
  errorEl.textContent = "";
}

function renderResult(data) {
  resultEl.hidden = false;
  reportBody.innerHTML = renderReport(data.report) || "<em>No report was produced.</em>";

  const revisions = data.revisions || 0;
  revisionBadge.textContent = revisions === 0 ? "passed first draft" : `${revisions} revision${revisions === 1 ? "" : "s"}`;
  revisionBadge.classList.toggle("pass", revisions === 0);

  const citations = data.citations || [];
  citationsList.innerHTML = "";
  if (citations.length) {
    citationsBlock.hidden = false;
    citations.forEach((c) => {
      const chip = document.createElement("span");
      chip.className = "citation-chip";
      const [kind, rest] = String(c).split(/:(.+)/s);
      chip.innerHTML = rest ? `<b>${escapeHtml(kind)}</b>:${escapeHtml(rest)}` : escapeHtml(c);
      citationsList.appendChild(chip);
    });
  } else {
    citationsBlock.hidden = true;
  }

  const trace = data.trace || [];
  traceList.innerHTML = "";
  trace.forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    traceList.appendChild(li);
  });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  clearError();
  resultEl.hidden = true;
  setLoading(true);
  statusText.textContent = "Running the agent graph…";

  try {
    const res = await fetch("/api/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`Request failed (${res.status}): ${body.slice(0, 300)}`);
    }

    const data = await res.json();
    renderResult(data);
  } catch (err) {
    showError(err.message || "Something went wrong.");
  } finally {
    setLoading(false);
  }
});
