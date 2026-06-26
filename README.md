# Minimal Agent

一个从零实现的最小可用 Agent。核心 runtime 自己实现，没有使用 LangChain、OpenHands、Spring AI、Dify、n8n 等现成 Agent 框架来完成主流程。

项目目标是展示一个 Agent 最小闭环：

- 接收用户输入
- 维护多轮 Session 和 Memory
- 调用真实 OpenAI-compatible LLM API
- 由 LLM 判断直接回答还是调用工具
- 执行工具并把结果回填给 LLM
- 循环执行，直到得到最终答案或达到最大步数
- 记录 trace，便于观察延迟、工具调用和 memory 召回

## 功能

- 多轮对话与 SQLite Session 持久化
- 真实 LLM API，兼容 OpenAI Chat Completions / tool calling 协议
- 自研 Agent runtime 主循环
- 4 个工具：`calculator`、`search`、`weather`、`todo`
- 最大步数限制与基础异常处理
- 跨轮次 Todo 任务状态维护
- 工具调用 trace 和延迟 trace
- Memory 并行召回、超时降级、上下文缓存
- Memory fast path / slow path 分层，慢来源可用缓存降级
- 按用户意图选择 memory 召回源，简单请求跳过不必要来源
- TaskContext 内置 CurrentStep，明确当前阶段、下一步和注意力边界
- Memory cache 使用来源版本指纹失效，trace 中可观察命中原因
- token 预算驱动的短期记忆裁剪
- 后台摘要压缩，避免用户请求链路阻塞
- SSE 阶段事件流式接口，降低前端等待感
- Web 聊天界面与右侧执行日志
- 使用 Fake LLM 的核心测试，不消耗真实 API Token

## 快速运行

项目兼容 Python 3.8+，建议使用 Python 3.11 或 3.12。

```powershell
cd D:\JAVA\boss
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`，至少设置：

```dotenv
LLM_API_KEY=你的真实 API Key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_MAX_TOKENS=800
AGENT_MAX_STEPS=6
AGENT_HISTORY_LIMIT=20
AGENT_CONTEXT_TOKEN_BUDGET=12000
AGENT_SUMMARY_TRIGGER_RATIO=0.5
AGENT_RECENT_TOKEN_BUDGET=5000
AGENT_TASK_CONTEXT_TOKEN_BUDGET=1500
AGENT_MEMORY_RECALL_TIMEOUT_MS=200
DATABASE_PATH=data/agent.db
```

如果使用 OpenAI 或其他兼容服务，只需要替换 `LLM_BASE_URL`、`LLM_MODEL` 和 `LLM_API_KEY`。

启动服务：

```powershell
python -m uvicorn app.main:app --reload
```

访问：

- Web 页面：<http://127.0.0.1:8000>
- API 文档：<http://127.0.0.1:8000/docs>

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## Demo 流程

在同一个 Session 中依次输入：

1. `计算 (18 + 6) * 4`
2. `帮我创建一个“准备 Agent 项目演示”的任务，并标记为进行中`
3. `刚才那个任务进度怎么样？`
4. `把它标记为完成`
5. `查询上海天气`

右侧 Trace 会展示：

- `memory_recall`
- `llm_request`
- `llm_response`
- `tool_parallel_start`
- `tool_result`
- `final_answer`
- `request_complete`

其中 `request_complete` 会记录总耗时、LLM 耗时、工具耗时和工具数量；`memory_recall` 会记录召回耗时、token 预算、缓存命中、上下文块保留/裁剪情况。

## 核心循环

核心代码位于 `app/agent/runtime.py`。

```text
save user message
build memory context
record memory trace

for step in max_steps:
    call llm
    if llm returns final answer:
        save answer
        return
    if llm returns tool calls:
        execute tools
        append tool results

return max steps reached
```

这个主循环没有依赖现成 Agent 框架。工具注册、工具执行、结果回填、trace、memory 构造和最大步数控制都由项目代码自己完成。

## 低延迟优化

这版根据面试沟通重点做了延迟优化：

1. Trace 拆解：记录 memory、LLM、tool、总请求耗时。
2. Memory 并行召回：summary、history、todo/task 同时读取。
3. Fast/slow path 分层：history 和 task 走 fast path，summary 走 slow path。
4. 意图选择召回源：简单计算/天气请求跳过 summary 和 task memory。
5. 召回超时降级：slow path 超时可用缓存摘要或空摘要继续执行。
6. 上下文优先级：TaskContext 优先保留，低优先级信息可裁剪。
7. CurrentStep 注入：明确当前任务阶段、下一步动作和不要做什么。
8. token 预算裁剪：不再按固定 10 轮截断，按 token 预算控制。
9. LLM 输出控制：通过 `LLM_MAX_TOKENS` 限制最大输出长度。
10. 只读工具并行：calculator/search/weather 可并行，todo 保持串行。
11. 上下文缓存：相同 session 的常用 memory context 可复用。
12. 版本化缓存失效：summary、todo、latest message 变化时刷新 memory cache。
13. 后台摘要压缩：摘要任务异步执行，不阻塞当前用户请求。
14. SSE 阶段流式：前端能更早看到开始状态和执行 trace。

## Memory 设计

Memory 召回发生在每次 `AgentRuntime.run` 保存当前用户消息之后、第一次 LLM 调用之前。

Prompt 结构：

```text
System Prompt
  |
Structured Memory Context
  |-- <TaskContext>
  |-- <RecentConversationPolicy>
  |-- <SessionSummary>
  `-- <MemoryBudget>
  |
Recent Conversation
```

关键设计：

- `SessionSummary` 承接长期压缩记忆。
- `TaskContext` 单独注入任务状态，不混入普通对话历史。
- 最近对话按 `AGENT_RECENT_TOKEN_BUDGET` 裁剪。
- 上下文块有优先级，任务状态优先于摘要和预算说明。
- 达到 `AGENT_CONTEXT_TOKEN_BUDGET * AGENT_SUMMARY_TRIGGER_RATIO` 后触发后台摘要压缩。

详细说明见 [docs/memory-design.md](docs/memory-design.md)。

## 项目结构

```text
app/
  agent/          LLM 客户端、Memory、Prompt、Runtime、Summary、Token Budget
  tools/          工具实现与注册中心
  static/         Web 页面
  database.py     SQLite schema
  repositories.py 持久化访问
  main.py         FastAPI 接口
tests/            单元测试
docs/             系统设计、Memory 设计、Prompt、开发记录、录屏脚本
```

## 已知边界

- `search` 和 `weather` 是题目允许的 mock 工具，不代表真实网络数据。
- SSE 当前是阶段事件流式，不是 token-by-token 的模型输出流式。
- token 估算使用轻量近似算法，不是模型官方 tokenizer。
- 当前 TaskContext 由 Todo 表承载，复杂业务可继续扩展为 Task / Step / Artifact 模型。
- LLM 服务需要支持 OpenAI 风格的 `tools` / `tool_calls`。

## 提交材料

- [提交说明](SUBMISSION.md)
- [系统设计](docs/system-design.md)
- [Memory 设计](docs/memory-design.md)
- [AI Prompt](docs/prompts.md)
- [AI Prompt 与问题解决记录](docs/ai-development-log.md)
- [录屏脚本](docs/demo-script.md)
