# Memory 召回与放置方式

## Memory 类型

### 对话 Memory

用户消息与 Agent 最终答案保存在 `messages` 表。每轮开始读取当前 Session 最近若干条，数量由 `AGENT_HISTORY_LIMIT` 控制。

### 状态 Memory

Todo 不依赖模型从自然语言历史中猜测，而是单独存入 `todos` 表。任务 ID、标题、状态、详情和更新时间均为结构化字段。

## 召回时机

召回位于 `AgentRuntime.run` 保存当前用户消息之后、第一次 LLM 调用之前。这样本轮输入和此前状态会被一次性组装。

## Prompt 中的位置

消息顺序如下：

1. 固定 System Prompt：角色、工具使用原则和停止条件。
2. 动态 System Message：当前 `session_id` 与结构化 Todo 列表。
3. 最近的用户与 Assistant 历史。

状态放在 System Message 是为了与普通对话区分，并向模型明确这些内容来自可信的应用状态。用户不能直接覆盖它。

## 跨轮继续执行

第一轮创建 Todo 后，工具将记录写入 SQLite。第二轮即使用户只说“刚才那个任务”，Memory 也会把当前 Session 的任务列表放入上下文，模型可读取任务 ID 和状态，再调用 `todo get/update`。

## 取舍

最小版本没有向量数据库。对于短对话，最近消息窗口足够；对于必须可靠延续的任务，结构化状态比语义检索更稳定。生产版本可增加摘要和向量召回，但不改变 Runtime 接口。

