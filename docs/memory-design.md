# Memory 设计

## 设计目标

本项目的 Memory 从最初的“按固定条数读取最近消息”升级为：

- 并行召回，降低用户等待时间。
- token 预算驱动，避免固定轮数导致上下文爆掉。
- session summary 承接长期压缩记忆。
- TaskContext 结构化注入，避免任务资料污染短期对话。
- 上下文块有优先级，重要信息优先保留。
- memory trace 可观测，便于继续优化延迟。

## Memory 类型

### Conversation Memory

用户消息和 Agent 最终回答保存在 `messages` 表。它们代表普通对话历史。

当前不会把工具中间消息长期持久化进普通对话历史，因为 OpenAI-compatible tool calling 对 `assistant tool_calls` 和 `tool` 消息有严格配对关系。只保存用户输入和最终回答，可以避免下一轮构造出不完整的工具调用历史。

### Session Summary

`sessions.summary` 保存压缩后的长期摘要。

当最近对话越来越长时，旧消息应该被压缩进 summary，而不是无限放进 prompt。当前项目已经实现：

- `Repository.get_session_summary`
- `Repository.update_session_summary`
- `<SessionSummary>` 注入位置
- `SummaryCompactor` 后台压缩
- `summary_compaction_scheduled` trace

### Task Memory

Todo / Task 状态保存在 `todos` 表。它不是普通聊天历史，而是结构化业务状态。

这些状态会注入到：

```text
<TaskContext>
...
</TaskContext>
```

这样模型可以知道当前任务是什么、进展如何，但不会把大量任务资料当成普通对话继续关注。

## 召回时机

召回发生在每次 `AgentRuntime.run` 保存当前用户消息之后、第一次 LLM 调用之前。

伪代码：

```python
repository.add_message(session_id, "user", user_input)
memory_result = memory.build(session_id)
trace.record(0, "memory_recall", output_data=memory_result.trace)
```

放在这个位置的原因：

- 当前用户输入已经进入本轮上下文。
- LLM 调用前可以拿到最新任务状态和历史摘要。
- 工具执行前就能让模型基于已有状态做决策。

## 放置方式

最终 prompt 顺序：

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

说明：

- `System Prompt` 放固定规则。
- `Structured Memory Context` 放动态记忆。
- `TaskContext` 优先级最高，保证跨轮任务状态不丢。
- `RecentConversationPolicy` 告诉模型如何理解短期历史和任务状态。
- `SessionSummary` 放长期压缩记忆。
- `MemoryBudget` 放 token 预算和裁剪信息。
- `Recent Conversation` 放最近用户和助手消息。

## 并行召回

`Memory._recall_parallel` 使用 `ThreadPoolExecutor` 同时读取：

- recent history
- session summary
- todos / task state

每个来源都有独立超时。某个来源失败或超时，不会让整个请求失败，而是在 trace 中记录降级信息。

在 SQLite demo 中收益有限，但真实业务里长期记忆可能来自向量库、业务数据库、搜索服务或远程文档系统，并行召回可以明显降低首轮等待时间。

## token 预算

项目新增 `app/agent/token_budget.py`：

- `estimate_tokens(text)`
- `estimate_message_tokens(message)`
- `estimate_messages_tokens(messages)`
- `trim_messages_to_budget(messages, max_tokens)`

当前为了轻量使用 `len(text) / 4` 近似估算 token。它不是精确 tokenizer，但足够解决“按固定 10 轮截断不稳定”的问题。

相关配置：

```dotenv
AGENT_CONTEXT_TOKEN_BUDGET=12000
AGENT_SUMMARY_TRIGGER_RATIO=0.5
AGENT_RECENT_TOKEN_BUDGET=5000
AGENT_TASK_CONTEXT_TOKEN_BUDGET=1500
```

含义：

- 总上下文预算约 12000 token。
- 最近对话达到总预算 50% 时建议压缩。
- 最近对话最多占 5000 token。
- 任务上下文最多占 1500 token。

## 上下文优先级

Memory 构造 `ContextBlock`：

| ContextBlock | 优先级 | 是否必保留 |
| --- | --- | --- |
| TaskContext | 1 | 是 |
| RecentConversationPolicy | 2 | 是 |
| SessionSummary | 3 | 否 |
| MemoryBudget | 4 | 否 |

当上下文过长时，低优先级块会先被裁剪或丢弃。这样即使历史很长，模型仍然优先知道“当前任务是什么、下一步要做什么”。

## 为什么 TaskContext 不直接放进短期记忆

面试中提到的 PPT 场景很典型：

```text
先查资料
再写文字
再做 PPT
```

如果第一步查到大量资料，并直接塞进普通 message history，模型很容易注意力偏移，不知道当前步骤到底要做什么。

因此本项目把任务状态作为 TaskContext 注入，并控制长度。大量原始资料未来应该进入 Artifact Store，只在 prompt 中注入摘要、引用和当前步骤，而不是把所有原文都放进短期记忆。

## 后台摘要压缩

当 `compaction_recommended=true` 时，Runtime 会调用 `SummaryCompactor.schedule_if_needed` 调度后台压缩。

这个设计的目的：

- 当前用户请求不等待摘要完成。
- 下一轮请求可以读取更新后的 summary。
- 压缩成本从主请求链路移到后台。

当前摘要算法是轻量确定性摘要，便于测试和演示；实际业务中可以替换为专门的总结模型。

## 可观测性

每轮请求都会记录 `memory_recall` trace，例如：

```json
{
  "recall_ms": 18,
  "cache_hit": false,
  "sources": {
    "history": {"ok": true, "duration_ms": 5},
    "summary": {"ok": true, "duration_ms": 3},
    "todos": {"ok": true, "duration_ms": 4}
  },
  "recent_message_tokens": 1800,
  "task_context_tokens": 300,
  "total_context_tokens": 2600,
  "context_token_budget": 12000,
  "compaction_recommended": false,
  "context_blocks": [
    {"name": "TaskContext", "kept": true},
    {"name": "SessionSummary", "kept": true}
  ]
}
```

这让 memory 优化不只是口头设计，而是可以在 Trace 中观察和验证。
