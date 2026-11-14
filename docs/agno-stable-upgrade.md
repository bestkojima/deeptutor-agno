# Agno 3.2.0 与 GPT-6 Luna 工具推理

项目锁定 Agno 3.2.0、OpenAI Python SDK 2.54.0。[Agno 3.2.0](https://github.com/agno-agi/agno/releases/tag/v3.2.0) 是正式版，不是预发布；官方发布于 2026-11-12 17:47 UTC，即北京时间 11 月 13 日 01:47。升级不重写工作台数据库、不要求全局安装，无需公开本机 `.env`。

## 为什么升级

- [Agno #9960](https://github.com/agno-agi/agno/issues/9960)：当无法使用 `previous_response_id`，旧版重发工具调用却漏掉相应推理条目，可能导致第二跳 400。
- [PR #10395](https://github.com/agno-agi/agno/pull/10395) 修复推理条目回放；[PR #10830](https://github.com/agno-agi/agno/pull/10830) 补上 GPT-6 识别。两处都已进入 [Agno v3.1.2](https://github.com/agno-agi/agno/releases/tag/v3.1.2)，本次选择后续正式版 [v3.2.0](https://github.com/agno-agi/agno/releases/tag/v3.2.0)。
- [OpenAI GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)：Chat Completions 的工具调用只支持 `reasoning_effort=none`，要配合 `high` 必须使用 Responses。之前的真实 Chat Completions 验收用的是旧版，并非本次升级后的线上验证。

## 配置与范围

默认保持低成本 Chat Completions。若要启用本次增加的可选路径，在**本地被忽略**的 `.env` 里设置：

```dotenv
AGNO_MODEL=gpt-6-luna
AGNO_DEEP_RESPONSES=1
```

用现有的 `uvicorn app.main:app --env-file ../.env --host 127.0.0.1 --port 8000` 从 backend/ 启动。只对 Solve 的求解阶段，以及 Research 的子题取证阶段启用 Responses/high。Chat、预览澄清、Research 规划和总结、审查和批阅不改。开关不设置或设为 0 即回退到 Chat Completions。

Responses 使用 `store=False`，不用 `previous_response_id`，关闭并行工具调用。Agno 在一个 Agent.run 内回放加密推理条目并按 call_id 匹配工具结果；应用不把这些条目写进 SSE、任务结果或检查点。高推理模式限制单次输出，不代表整个多分支任务有独立美元预算，不要在尚未验收时默认打开。

## 升级回归

- 新版 Workflow 对步骤异常的默认行为会跳过。主链已显式设为失败停止；没有可引用证据的 Research 不会继续调用报告 Agent。
- 使用真实 Agno 3.2.0 打包请求，模拟 OpenAI HTTP 响应：第 1 跳 `high` + 工具定义，模型给出加密推理条目与函数调用；第 2 跳带回推理条目、原调用和匹配的工具结果，最终得到 Pydantic 结构化答案。不再携带旧版私有方法补丁。
- 这不代表 OpenAI 线上 Responses 已通过。下一次真实验收应先跑同样的两跳最小用例，再验证 Solve 状态工具和 Research 子分支。
