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
  return element;
}

function setMessage(element, content) {
  element.querySelector("p").textContent = content;
  messages.scrollTop = messages.scrollHeight;
}

function appendTrace(item) {
  const placeholder = traces.querySelector(".muted");
  if (placeholder) traces.innerHTML = "";
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
  stepCount.textContent = `${traces.querySelectorAll(".trace").length} events`;
}

function renderTraces(items) {
  traces.innerHTML = "";
  stepCount.textContent = `${items.length} events`;
  if (!items.length) {
    traces.innerHTML = '<p class="muted">本轮没有执行记录。</p>';
    return;
  }
  items.forEach(appendTrace);
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
  const pending = appendMessage("assistant", "正在连接 Agent...");
  pending.classList.add("pending");
  renderTraces([]);

  try {
    await streamChat(content, pending);
    await loadSessions();
  } catch (error) {
    setMessage(pending, `请求失败：${error.message}`);
  } finally {
    pending.classList.remove("pending");
    state.busy = false;
    sendButton.disabled = false;
    input.focus();
  }
}

async function streamChat(content, pending) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: content,
      session_id: state.sessionId,
    }),
  });
  if (!response.ok || !response.body) {
    throw new Error("流式请求失败");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      handleSseEvent(part, pending);
    }
  }
  if (buffer.trim()) {
    handleSseEvent(buffer, pending);
  }
}

function handleSseEvent(raw, pending) {
  const lines = raw.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLine = lines.find((line) => line.startsWith("data:"));
  if (!eventLine || !dataLine) return;
  const event = eventLine.slice("event:".length).trim();
  const data = JSON.parse(dataLine.slice("data:".length).trim());

  if (event === "start") {
    state.sessionId = data.session_id;
    localStorage.setItem("minimal-agent-session", data.session_id);
    setMessage(pending, "已开始执行，正在召回 memory...");
  } else if (event === "trace") {
    appendTrace(data);
    setMessage(pending, stageText(data.event));
  } else if (event === "answer") {
    state.sessionId = data.session_id;
    localStorage.setItem("minimal-agent-session", data.session_id);
    setMessage(pending, data.answer);
  } else if (event === "error") {
    throw new Error(data.detail || "请求失败");
  }
}

function stageText(event) {
  const labels = {
    memory_recall: "Memory 召回完成...",
    llm_request: "正在请求 LLM...",
    llm_response: "LLM 已返回，正在判断下一步...",
    tool_parallel_start: "正在并行执行只读工具...",
    tool_call: "正在调用工具...",
    tool_result: "工具结果已返回...",
    final_answer: "正在整理最终回答...",
    request_complete: "请求完成。",
  };
  return labels[event] || `正在执行：${event}`;
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
