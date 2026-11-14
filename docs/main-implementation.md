# 当前主线：能力与代码入口

依赖锁定 Agno 3.2.0 / OpenAI Python SDK 2.54.0。上游对照采用 DeepTutor v1.7.2；[固定提交上的逐项源码对照](deeptutor-agno-code-map.md)记录的是历史基线，本页补上当前代码落点。这里是行为复现，不是全量兼容。

## 共用链路

`POST /api/tasks` → [create_task → execute](../backend/app/main.py) → [run_agno](../backend/app/agno_adapter.py) → Agno Workflow 的 Step / Loop / Parallel。工具调用的开始、完成和失败写入任务事件，前端用 SSE 显示轨迹与进度。本地 SQLite 保存任务状态；不是账户级长期记忆。

| 能力 | 当前实现和代码入口 | 与上游的差异 |
| --- | --- | --- |
| Chat | [run_agno / ask_model](../backend/app/agno_adapter.py) 绑定已注册工具、解析结构化输出并复核 | 不加载任意插件，不执行模型代码 |
| Ask Questions | [prepare_preview / confirmed_inputs](../backend/app/preview.py) 生成并校验澄清卡 → [resume_task](../backend/app/main.py) 续做同一任务；不把第二张卡当结果 | 恢复同一业务任务，并非恢复供应商的调用栈 |
| Quiz | [generate_quiz](../backend/app/quiz_workflow.py) 逐题生成与验证 → [quiz_delivery](../backend/app/quiz_delivery.py) 写入题目和私有答案 → 提交后服务端判分 | 单选、多选精确匹配；填空/简答进入人工复核，而非由模型暗中直接给分 |
| Visualize | [render_function_graph](../backend/app/visualize.py) 计算采样并绘图 → [界面](../frontend/app.js) 滑块重算二次曲线并拒绝旧响应 | 无任意生成 HTML、TSX 或 Manim 执行；交互范围有限 |
| Video Lesson | [build_lesson](../backend/app/media.py) 渲染分镜 → MP4/VTT；[build_math_lesson](../backend/app/math_lesson_media.py) 支持受控二次函数动画，失败修订保留可播放版本 | FFmpeg 不是上游 Remotion；没有任意可执行课件或实时 TTS 验收 |
| Immersive Reading | [字幕导入](../backend/app/source_ingestion.py) → [read_excerpt / locate_excerpt](../backend/app/agno_adapter.py) → [阅读界面](../frontend/reader.js) 高亮匹配的引文，并为受控媒体定位 | 不做原始素材的 OCR、ASR 或持久批注 |
| Research | 提纲确认 → [research_evidence_stage](../backend/app/research_workflow.py) 并行取证 → [ResearchCheckpoint](../backend/app/research_checkpoint.py) 保存分支 → 合成与复核；中断后用原任务 ID 显式续跑 | 只有单服务进程的持久恢复；远程调用不保证恰好一次，引文匹配也不证明论点成立 |
| Solve | [SolveState](../backend/app/solve_workflow.py) 管理规划、步骤和有限重规划 → [run_agno](../backend/app/agno_adapter.py) 求解与复核 | 并非形式化证明；求解步骤不跨重启恢复 |
| Exam | [主编 Team → 题型 Team → 出题 Agent](exam-team-workflow.md) → [蓝图约束与校验](../backend/app/exam_blueprint.py) → [prepare_canonical / build_exam_artifacts](../backend/app/exam_artifacts.py) → 学生与答案 PDF、Markdown、TeX 和同一 TikZ 来源的 SVG | 自有能力。结构校验不保证数学正确或难度等价；暂不自动解析样卷 PDF、不接记忆；任意模型 TeX 不执行 |

## 怎么验收

- [Exam 团队编排、轨迹及显式回退](exam-team-workflow.md)。

- [最新实施验收和实测边界](implement-spec-results.md)：区分真实 Luna Chat Completions、离线工作流、实编译与实编码。
- [Agno 升级与可选 Responses/high](agno-stable-upgrade.md)：仅对 Solve 求解和 Research 子题取证开启；原有默认路径不改。
- [Exam 导出请求、安装依赖与复验](../examples/exam-artifacts/README.md)：教师 ZIP 含答案，不分发给学生。固定结构测试夹具不等于真实自动出题质量。
