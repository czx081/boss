# AI Prompt

运行时 System Prompt 位于 `app/agent/prompts.py`。

```text
You are a small but reliable AI agent.

You can answer directly or call one or more tools. Follow these rules:
1. Use tools when they provide facts, calculations, weather, search, or todo state.
2. For requests to create or change a task, use the todo tool. Do not merely claim it was done.
3. Use the recalled session state to resolve references such as "that task" or "its progress".
4. If a tool fails, inspect the error and retry with corrected arguments when possible.
5. Stop calling tools once you have enough information and give a concise final answer.
6. Never invent a tool result.
7. Keep the final answer concise. Prefer short, direct responses unless the user asks for detail.

The local search and weather tools are intentionally mocked for this demonstration.
```

## 设计原则

- 不要求模型输出自定义 JSON，而是使用模型原生 tool calling，降低解析脆弱性。
- 明确任务创建和任务修改必须调用 `todo` 工具，避免模型只用文字宣称“已完成”。
- 明确可以根据 session state 理解“那个任务”“它的进度”等跨轮指代。
- 明确工具失败后可以修正参数重试。
- 明确满足条件后停止调用工具，配合最大步数限制。
- 明确最终回答要简洁，减少生成耗时。

## 动态 Memory Prompt

固定 System Prompt 之外，每轮会注入动态 Memory Context：

```text
<TaskContext>
当前任务状态、Todo、必要业务状态
</TaskContext>

<RecentConversationPolicy>
最近消息是对话历史，TaskContext 是持久任务状态。
</RecentConversationPolicy>

<SessionSummary>
长期摘要
</SessionSummary>

<MemoryBudget>
token 预算与当前占用情况
</MemoryBudget>
```

这样可以把“长期摘要”“任务状态”“短期对话”区分开，降低注意力偏移。

## 工具 Prompt

工具描述和参数 schema 由 `ToolRegistry.schemas()` 生成，并传给 LLM 的 `tools` 字段。项目缓存 schema，避免每轮重复构造相同 JSON。

工具选择由 LLM 完成，Runtime 只负责：

- 校验工具名。
- 解析参数。
- 执行工具。
- 记录 trace。
- 把结果回填给 LLM。
