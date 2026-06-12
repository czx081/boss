# 系统设计

## 目标

实现一个可运行、可观察、可持久化的最小 Agent，重点证明 Agent runtime 的主循环由项目自身实现。

## 组件

```text
Browser
  |
FastAPI API
  |
AgentRuntime
  |-- Memory -------- SQLite(messages, todos)
  |-- LLMClient ----- OpenAI-compatible API
  |-- ToolRegistry -- calculator/search/weather/todo
  `-- TraceRecorder - SQLite(traces)
```

## 请求生命周期

1. `/api/chat` 创建或校验 Session。
2. Runtime 保存用户消息。
3. Memory 组装 System Prompt、Session 状态和历史消息。
4. LLMClient 通过 HTTP 请求真实模型。
5. Runtime 检查模型是否返回 `tool_calls`。
6. ToolRegistry 校验工具名并分发调用。
7. 结果作为 `role=tool` 消息加入当前上下文。
8. Runtime 继续步骤 4，直至模型返回最终文本。
9. 最终答案和 Trace 写入 SQLite。

## 数据模型

- `sessions`：Session 标识、标题和更新时间。
- `messages`：跨轮用户消息和最终回答。
- `todos`：Session 范围内的持久业务状态。
- `traces`：单次请求每一步的输入摘要、工具参数、结果和错误。

## 安全与可靠性

- `AGENT_MAX_STEPS` 防止无限循环。
- Calculator 通过 AST 白名单执行，不使用 `eval`。
- 工具注册表拒绝未知工具。
- JSON 参数解析、工具异常和 LLM HTTP 异常分别处理并记录。
- Todo 查询始终带 `session_id`，避免不同 Session 串数据。

## 扩展方式

新工具只需实现普通函数并在 `ToolRegistry` 中注册 JSON Schema。替换模型服务只需修改 `.env` 中的 URL、Key 和模型名。

