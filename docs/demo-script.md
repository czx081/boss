# 操作录屏脚本

建议录屏 3 到 5 分钟。

1. 展示项目目录和 README，说明核心 runtime 没有使用现成 Agent 框架。
2. 展示 `.env.example`，说明真实 Key 放在本地 `.env`，不会提交。
3. 运行服务：

   ```powershell
   python -m uvicorn app.main:app --reload
   ```

4. 打开 <http://127.0.0.1:8000>。
5. 输入：`计算 (18 + 6) * 4`，展示 calculator trace。
6. 输入：`帮我创建一个“准备 Agent 项目演示”的任务，并标记为进行中`。
7. 输入：`刚才那个任务进度怎么样？`，说明 Todo 状态跨轮召回。
8. 输入：`把它标记为完成`，展示 todo update trace。
9. 输入：`查询上海天气`，说明 weather 是题目允许的 mock 工具。
10. 展示右侧 trace 中的 memory、LLM、tool 和 request_complete 延迟信息。
11. 打开 `/docs` 简短展示 API。
12. 在终端运行：

    ```powershell
    python -m unittest discover -s tests -v
    ```

13. 说明面试后新增的低延迟优化：并行召回、token 预算、后台摘要、SSE 阶段流式。

录屏时避免展示 `.env` 内容或 API Key。
