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

TaskContext 内部还包含 `current_step`：

```json
{
  "current_step": {
    "task_id": 2,
    "task_title": "make product research PPT",
    "phase": "working",
    "status": "in_progress",
    "next_action": "Continue the current task from its latest known state.",
    "avoid": "Do not treat raw research, old details, or completed steps as the current objective."
  }
}
```

`current_step` 会优先选择 `in_progress` 任务，其次是 `pending`、`completed`、`cancelled`。它的作用是把模型注意力拉回“当前阶段、下一步动作、不要做什么”，而不是只给模型一堆任务列表。

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

## Fast Path / Slow Path

Memory 召回不是所有来源都同等重要。为了降低主链路等待时间，项目把召回源分成两类：

| 路径 | 来源 | 策略 |
| --- | --- | --- |
| Fast Path | recent history、todos / task state | 当前轮决策强相关，优先同步进入 prompt |
| Slow Path | session summary | 可能有帮助，但允许使用缓存或空摘要降级 |

当前实现中，summary 仍然会和 fast path 并行请求；如果 summary 在本轮超时，则使用上一轮缓存的 summary。如果没有缓存，就使用空摘要。这样可以保证用户请求继续向前走，而不是为了低频长期记忆一直等待。

Trace 中会记录：

```json
{
  "recall_strategy": {
    "fast_path": ["history", "todos"],
    "slow_path": ["summary"]
  },
  "sources": {
    "history": {"path": "fast", "status": "ok"},
    "todos": {"path": "fast", "status": "ok"},
    "summary": {
      "path": "slow",
      "status": "timeout",
      "fallback_used": true,
      "cache_fallback_available": true
    }
  }
}
```

面向真实业务时，可以继续把向量库、远程文档、历史长对话检索放进 slow path，并通过后台预取或缓存让下一轮请求受益。

## 按意图选择召回源

最快的 memory 召回是不召回。项目在每轮请求开始时，会用轻量规则判断本轮用户输入大致属于哪类意图，避免为了简单请求读取不必要的长期记忆。

当前规则不额外调用 LLM，因此不会引入新的模型延迟：

| 用户意图 | 示例 | 召回策略 |
| --- | --- | --- |
| `simple_tool` | `计算 (1+2)*3`、`查询上海天气` | 只召回 recent history，跳过 summary 和 todos |
| `task_related` | `刚才那个任务进度怎么样` | 召回 recent history 和 todos，默认跳过 summary |
| `history_related` | `总结一下我们之前聊过什么` | 召回 recent history 和 summary，跳过 todos |
| `default_light` | 普通问答 | 召回 recent history 和 todos，跳过 summary |
| `default_full` | 未传入用户输入的兼容路径 | 召回全部来源 |

Trace 中会记录 `recall_plan`：

```json
{
  "recall_plan": {
    "intent": "simple_tool",
    "sources": {
      "history": true,
      "summary": false,
      "todos": false
    }
  }
}
```

这个设计的核心不是“规则多聪明”，而是把召回做成可选择的 pipeline。真实业务中可以继续替换为更复杂的 intent classifier，但仍然要遵守一个原则：简单请求不要为低概率有用的 memory 支付固定延迟。

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

`current_step` 专门服务于这个场景：

- `phase` 告诉模型当前处于资料调研、执行中、已完成等状态。
- `next_action` 告诉模型下一步该做什么。
- `avoid` 明确提醒模型不要把旧资料、已完成步骤或大量原文当成当前目标。

所以在“先查资料，再写文字，再做 PPT”的链路中，即使第一步产生很多资料，prompt 中仍然会有一个短而明确的当前步骤锚点。

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

## 版本化缓存失效

Context cache 不再简单依赖整段 summary / todos 内容拼接，而是使用来源版本指纹：

```json
{
  "cache_versions": {
    "summary_version": "2f1a0c8d...",
    "todo_version": "91bc32a1...",
    "latest_message_version": "aa73c991..."
  },
  "context_blocks": {
    "cache_key_strategy": "source_versions",
    "cache_hit": true
  }
}
```

当前版本指纹来自已经召回的数据，不额外增加数据库查询：

- `summary_version`：summary 文本短指纹。
- `todo_version`：todo 的 id、title、status、details、updated_at 短指纹。
- `latest_message_version`：最近一条消息短指纹。

这样做的好处是：

- summary 变化时只让相关上下文失效。
- todo 状态变化时及时刷新 TaskContext。
- 最新消息变化时刷新和本轮上下文相关的预算信息。
- trace 中可以解释为什么缓存命中或失效。

真实线上系统里，这些指纹可以替换为数据库行版本、递增 revision、binlog offset 或缓存系统里的版本号，进一步减少 hash 计算成本。
