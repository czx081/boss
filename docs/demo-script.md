# 操作录屏脚本

建议录屏 3 至 5 分钟。

1. 展示项目目录和 README，说明核心 runtime 未使用 Agent 框架。
2. 运行 `uvicorn app.main:app --reload`，打开网页。
3. 输入 `计算 (18 + 6) * 4`，展示右侧 Calculator Trace。
4. 输入 `帮我创建一个“准备 Agent 项目演示”的任务，并标记为进行中`。
5. 输入 `刚才那个任务进度怎么样？`，说明 Todo 状态跨轮召回。
6. 输入 `把它标记为完成`，展示 Todo Update Trace。
7. 输入 `查询上海天气`，说明 Weather 是题目允许的 mock。
8. 点击“新建 Session”，输入 `有哪些任务？`，展示 Session 隔离。
9. 打开 `/docs` 简短展示 API。
10. 在终端运行 `python -m unittest discover -s tests -v`，展示测试通过。

录屏时避免展示 `.env` 内容或 API Key。
