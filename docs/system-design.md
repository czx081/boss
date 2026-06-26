# 系统设计

## 目标

实现一个不依赖 LangChain、OpenHands、Spring AI 等现成 Agent 框架的最小可用 Agent。核心目标：

- 自己实现 Agent runtime 主循环。
- 接入真实 OpenAI-compatible LLM API。
- 支持多轮 Session 和跨轮任务状态。
- 支持工具调用、工具结果回填和 trace。
- 支持 Memory 召回、上下文预算和低延迟优化。

## 总体架构

```text
Browser
  |
FastAPI
  |-- /api/chat
  |-- /api/chat/stream
  |
AgentRuntime
  |-- Memory
  |     |-- parallel recall
  |     |-- context cache
  |     |-- token budget
  |     |-- task context
  |     `-- session summary
  |
  |-- LLMClient
  |     `-- OpenAI-compatible Chat Completions
  |
  |-- ToolRegistry
  |     |-- calculator
  |     |-- search
  |     |-- weather
  |     `-- todo
  |
  |-- SummaryCompactor
  |     `-- background summary
  |
  |-- Repository
  |     `-- SQLite
  |
  `-- TraceRecorder
```

## 请求生命周期

1. API 创建或校验 Session。
2. Runtime 保存当前用户消息。
3. Memory 并行召回 summary、recent messages、todo/task。
4. Memory 按 token budget 裁剪最近对话和任务上下文。
5. Memory 构造结构化上下文。
6. Runtime 写入 `memory_recall` trace。
7. 如达到压缩阈值，调度后台 summary compaction。
8. Runtime 调用真实 LLM。
9. 如果 LLM 返回最终答案，保存并返回。
10. 如果 LLM 返回 `tool_calls`，Runtime 校验参数并执行工具。
11. 只读且可并行的工具并发执行，写操作工具串行执行。
12. 工具结果作为 `tool` 消息回填给 LLM。
13. 循环执行，直到最终回答或达到 `AGENT_MAX_STEPS`。

## Runtime 主循环

核心循环位于 `app/agent/runtime.py`。

```text
save user message
build memory
record memory_recall trace

for step in max_steps:
    call llm
    record llm_request / llm_response trace

    if final answer:
        save assistant message
        record final_answer / request_complete trace
        return answer

    execute tool calls
    append tool result messages

record max_steps_reached
return fallback answer
```

这个循环只使用普通 Python、HTTP 请求、JSON 数据结构和本项目自己的类。

## 工具系统

工具通过 `ToolRegistry` 注册，每个工具包含：

- `name`
- `description`
- JSON Schema 参数
- handler
- 是否需要 `session_id`
- 是否只读
- 是否允许并行
- 风险等级

当前工具：

- `calculator`：安全数学计算，使用 AST 白名单，不使用 `eval`。
- `search`：mock 搜索，演示外部信息获取。
- `weather`：mock 天气，演示结构化查询。
- `todo`：跨轮任务状态管理。

只读低风险工具可以并行执行；`todo` 会修改状态，因此保持串行。

## Memory Manager

Memory 位于 `app/agent/memory.py`，负责：

- 并行召回 history、summary、todos。
- 对每个召回源设置超时。
- 构造 TaskContext、SessionSummary、MemoryBudget。
- 按上下文块优先级做预算裁剪。
- 生成 memory trace。
- 缓存常用上下文，减少重复构造成本。

token 工具位于 `app/agent/token_budget.py`。

## 数据模型

- `sessions`：Session 标识、标题、summary、创建和更新时间。
- `messages`：用户消息和 Agent 最终回答。
- `todos`：Session 范围内的持久任务状态。
- `traces`：每次请求的 memory、LLM、tool、error、final answer 和 latency 记录。

## 延迟优化设计

面试反馈重点关注“降低延迟、减少用户等待”。项目对应做了以下改造：

| 优化点 | 作用 |
| --- | --- |
| 延迟 trace | 定位耗时来自 memory、LLM 还是 tool |
| memory 并行召回 | 多个来源同时读取，降低首轮等待 |
| 召回超时降级 | 单个慢来源不拖垮整体请求 |
| token 预算裁剪 | 避免固定轮数导致 prompt 过长 |
| 上下文优先级 | 任务状态优先保留，低价值内容可裁剪 |
| 只读工具并行 | 多个独立工具调用同时执行 |
| schema/context cache | 减少重复 JSON Schema 与 memory context 构造 |
| 后台摘要压缩 | 压缩不阻塞用户当前请求 |
| SSE 阶段流式 | 前端更快看到开始状态和执行过程 |
| LLM max_tokens | 限制输出长度，控制生成耗时 |

## API

- `GET /`：Web 页面。
- `GET /health`：健康检查。
- `GET /api/sessions`：Session 列表。
- `POST /api/chat`：普通聊天接口。
- `POST /api/chat/stream`：SSE 阶段事件流式接口。

SSE 事件：

- `start`
- `trace`
- `answer`
- `done`
- `error`

## 安全与可靠性

- `AGENT_MAX_STEPS` 防止无限循环。
- Calculator 不使用 `eval`。
- 未知工具会被拒绝。
- 工具参数解析失败会进入 trace，并作为错误结果回填给 LLM。
- Todo 始终带 `session_id`，避免跨 Session 串数据。
- LLM API 异常会记录 trace，并返回可读错误。
- `.env`、API Key、数据库文件不进入 Git。

## 后续扩展

如果继续向业务 Agent 框架演进，可以增加：

- Planner / Executor / Evaluator
- Task / Step / Artifact 数据模型
- Artifact Store
- 向量库和 RAG
- Human Approval
- 工具权限与风险等级审批
- Prompt 版本管理
- 成本、token、延迟统计面板
- 真正 token-by-token 的 LLM 流式输出
