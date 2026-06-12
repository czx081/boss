const state = {
  sessionId: localStorage.getItem("minimal-agent-session"),
  busy: false,
};

const messages = document.querySelector("#messages");
const traces = document.querySelector("#traces");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const sessions = document.querySelector("#sessions");
const health = document.querySelector("#health");
const stepCount = document.querySelector("#step-count");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function appendMessage(role, content) {
  const welcome = messages.querySelector(".welcome");
  if (welcome) welcome.remove();
  const element = document.createElement("article");
  element.className = `message ${role}`;
  element.innerHTML = `
    <span>${role === "user" ? "YOU" : "AGENT"}</span>
    <p>${escapeHtml(content)}</p>
  `;
  messages.appendChild(element);
  messages.scrollTop = messages.scrollHeight;
}

function renderTraces(items) {
  traces.innerHTML = "";
  stepCount.textContent = `${items.length} events`;
  if (!items.length) {
    traces.innerHTML = '<p class="muted">本轮没有执行记录。</p>';
    return;
  }
  items.forEach((item) => {
    const element = document.createElement("article");
    element.className = `trace ${item.error ? "error" : ""}`;
    const detail = item.error || item.output || item.input;
    element.innerHTML = `
      <div class="trace-row">
        <strong>${escapeHtml(item.event)}</strong>
        <span>STEP ${item.step}</span>
      </div>
      ${item.name ? `<code>${escapeHtml(item.name)}</code>` : ""}
      ${detail ? `<pre>${escapeHtml(JSON.stringify(detail, null, 2))}</pre>` : ""}
    `;
    traces.appendChild(element);
  });
}

async function loadHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    health.className = `health ${data.llm_configured ? "ready" : "warning"}`;
    health.textContent = data.llm_configured
      ? `LLM ready · ${data.model}`
      : "LLM API key 未配置";
  } catch {
    health.className = "health warning";
    health.textContent = "服务连接失败";
  }
}

async function loadSessions() {
  const response = await fetch("/api/sessions");
  if (!response.ok) return;
  const data = await response.json();
  sessions.innerHTML = "";
  data.forEach((session) => {
    const button = document.createElement("button");
    button.className = session.id === state.sessionId ? "session active" : "session";
    button.textContent = session.title;
    button.title = "选择后，新消息会继续写入这个 Session";
    button.addEventListener("click", () => {
      state.sessionId = session.id;
      localStorage.setItem("minimal-agent-session", session.id);
      messages.innerHTML = `
        <div class="welcome">
          <p class="eyebrow">SESSION SELECTED</p>
          <h2>${escapeHtml(session.title)}</h2>
          <p>已恢复该 Session。继续提问时，Agent 会召回历史和任务状态。</p>
        </div>`;
      renderTraces([]);
      loadSessions();
    });
    sessions.appendChild(button);
  });
}

async function sendMessage(content) {
  if (state.busy) return;
  state.busy = true;
  sendButton.disabled = true;
  appendMessage("user", content);
  const pending = document.createElement("article");
  pending.className = "message assistant pending";
  pending.innerHTML = "<span>AGENT</span><p>正在执行...</p>";
  messages.appendChild(pending);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: content,
        session_id: state.sessionId,
      }),
    });
    const data = await response.json();
    pending.remove();
    if (!response.ok) {
      throw new Error(data.detail || "请求失败");
    }
    state.sessionId = data.session_id;
    localStorage.setItem("minimal-agent-session", data.session_id);
    appendMessage("assistant", data.answer);
    renderTraces(data.traces);
    await loadSessions();
  } catch (error) {
    pending.remove();
    appendMessage("assistant", `请求失败：${error.message}`);
  } finally {
    state.busy = false;
    sendButton.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content) return;
  input.value = "";
  sendMessage(content);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelector("#new-session").addEventListener("click", () => {
  state.sessionId = null;
  localStorage.removeItem("minimal-agent-session");
  messages.innerHTML = `
    <div class="welcome">
      <p class="eyebrow">NEW SESSION</p>
      <h2>新的上下文</h2>
      <p>下一条消息会创建独立 Session。</p>
    </div>`;
  renderTraces([]);
  loadSessions();
});

loadHealth();
loadSessions();
input.focus();

