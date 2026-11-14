# DeepTutor 与 Agno 实现逐项对照

当前代码入口和增量见[主线实现](main-implementation.md)。规格见 [#8](https://github.com/bestkojima/deeptutor-agno/issues/8)。这里说明代码怎么跑，不替代规格或验收工单。

**固定基线**：上游 DeepTutor v1.7.2（`60fb3bd`），本项目公开提交 `c6fc527`，依赖 Agno 2.3.21。下文所有源码链接均固定到这两个提交。状态指这一基线，不把 #1–#7 的计划写成已完成。

## 公共入口：从请求到结果

- **DeepTutor：** Chat 等能力复用 [AgenticLoopPipeline](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/runtime/agentic/loop.py)；Quiz、Research、Video 另有专用管线。
- **Agno：** [create_task](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/main.py#L152-L166) → [execute](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/main.py#L61-L107) → [run_agno](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L77-L107)。FastAPI 接收任务、SQLite 实时记事件、[events 回放 SSE](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/main.py#L189-L202)。各能力分别选择普通 Step、Loop 或 Parallel；本地状态并非 Agno 的模型会话栈。

## 1. Chat｜工具式对话

- **DeepTutor：** [AgenticChatPipeline](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/chat/agentic_pipeline.py#L36) 绑定共享工具循环：组装上下文 → 调模型 → 分发工具 → 回填结果。
- **Agno：** [ask_model](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L232-L245) 为 Agent 绑定允许的工具并解析结果；[检索与计算工具](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L133-L177) 记录开始/完成/失败；[answer → review](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L327-L355) 复核。
- **边界：** 保留工具循环，新增模型复核；没有复制全量插件和工作区。真实 provider 尚未验收（#1）。

## 2. Ask Questions｜澄清再续做

- **DeepTutor：** [AskQuestionsCapability.run](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/ask_questions/capability.py#L22-L32) 在选中回合首轮强制 ask_user，然后回共享对话循环完成原任务。
- **Agno：** [prepare_preview](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/preview.py#L51-L78) 产生类型化卡片 → [execute 暂停](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/main.py#L61-L76) → [confirmed_inputs](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/preview.py#L87-L105) 验证必填与选项 → [resume_task](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/main.py#L173-L187) 用同一任务 ID 重启执行 → [续做指令和交付门禁](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L205-L213)；[拒绝第二张卡充当结果](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L369-L371)。
- **边界：** 同一业务任务续做，不是恢复同一个模型调用栈。

## 3. Quiz｜练习题

- **DeepTutor：** [_run_inner](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/question/pipeline.py#L515-L613) 普通探索→规划，模板模式跳过；[_quiz_one / _repair_quiz_payload](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/question/pipeline.py#L876-L1040) 逐题生成、校验、修复；[_emit_quiz_question](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/question/pipeline.py#L1290-L1383) 发题及汇总。
- **Agno：** [quiz_executor](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L285-L326) 选规划或模板，调用生成/复核 Agent → [generate_quiz](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/quiz_workflow.py#L10-L77) 校验题型、去重、最多再试一次、逐题发事件并记录失败。
- **边界：** 独立探索与规划合并为一个规划 Agent；本地四类题型不等同上游全量。可作答界面和客观反馈属于 #2。

## 4. Visualize｜数学图

- **DeepTutor：** [VisualizeCapability.run](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/visualize/capability.py#L89-L260) 选工具路径或 Manim 路径，[SubmitVisualizationTool.execute](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/visualizers/tool.py#L64-L143) 调插件校验并提交产物。
- **Agno：** [submit_visualization](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L183-L200) 拒绝并反馈非法图 → [finalize_visual](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/visualize.py#L6-L44) 或 [render_function_graph](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/visualize.py#L69-L127) 计算并输出 SVG → [compute_plot](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/main.py#L118-L124) 可无模型重算。
- **边界：** 只支持白名单图形；没有活动 HTML、Manim 和交互视图。拖动界面与竞态处理属于 #3。

## 5. Video Lesson｜微课

- **DeepTutor：** [VideoLessonCapability.run](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/video_lesson/capability.py#L25-L244) 生成 TSX → Remotion 构建 → 有界修复与布局检查 → 必要时退回上一可播放版。
- **Agno：** [render_lesson](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L341-L355) 在分镜通过复核后调用 [build_lesson](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/media.py#L66-L159)：Pillow 画帧、FFmpeg 生成 MP4 及 VTT，旁白可选。
- **边界：** FFmpeg 幻灯片是替代实现，并非 Remotion；固定动画模板、失败回退属于 #6，未验证实时 TTS。

## 6. Immersive Reading｜阅读引用

- **DeepTutor：** [ReadingCapability](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/reading/capability.py#L323-L455) 将阅读上下文交给预处理与主循环；[read / goto / annotate](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/reading/tools.py#L311-L522) 负责读、导航和批注。
- **Agno：** [ingest_source](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/source_ingestion.py#L38-L99) 转换 VTT/SRT；[read_excerpt / locate_excerpt](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L110-L132) 仅访问附加材料，精确匹配后发 reader.located；[verify_citations](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L59-L74) 校验来源。
- **边界：** 已有定位事件，无阅读器跳转和高亮（#4）；不提供 ASR、OCR、持久批注。

## 7. Research｜分支研究

- **DeepTutor：** [DeepResearchCapability.run](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/research/capability.py#L37-L89) → [_run_inner](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/research/pipeline.py#L565-L722) 改写、分解、确认提纲 → [_drive_queue / _write_report](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/research/pipeline.py#L1168-L1320) 分块取证与汇总。
- **Agno：** [prepare_preview / confirmed_inputs](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/preview.py#L51-L108) 审核提纲 → [evidence_executor](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L262-L284) → [research_evidence_stage](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/research_workflow.py#L94-L175) 用 Agno Parallel，最多六支、顺序聚合、记录缺口。
- **边界：** 全部无有效引用时不发报告。确认前本项目不调用工具，与上游改写阶段不同；中断恢复属于 #5。引用匹配不是论点蕴含证明。

## 8. Solve｜按步骤解题

- **DeepTutor：** [DeepSolveCapability.run](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/solve/capability.py#L65-L84) 复用 Chat；[SolveSession](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/solve/session.py#L40-L79) 和 [规划、完成、重规划工具](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/solve/tools.py#L110-L295) 管理进度。
- **Agno：** [SolveState](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/solve_workflow.py#L39-L103) 校验下一步与重规划预算 → [solve 工具绑定](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/solve_workflow.py#L103-L135) → [answer / review Loop](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L327-L338) → [require_complete 门禁](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/agno_adapter.py#L365-L368)。
- **边界：** 本项目保留已完成前缀、超十二步直接拒绝；上游重规划整体替换并截断。两轮复核和两次重规划是不同预算，步骤摘要没有跨重启恢复。

## 9. Exam｜整卷（自有能力）

- **DeepTutor：** 无直接对等入口。上游 Quiz 的模板练题不是整卷审阅、编号和多格式导出。
- **Agno：** [generation_contract 与 validate_generated_exam](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/exam_blueprint.py#L130-L200) 定义并核对结构与答案对应 → [render_exam](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/backend/app/exam_blueprint.py#L241) 已能输出基础文本；[2026 Ⅰ卷样式源码](https://github.com/bestkojima/deeptutor-agno/blob/c6fc527d70504547a889ee8f4569effc4b320e34/examples/latex-gaokao-i-2026) 可用 XeLaTeX 独立编译。
- **边界：** 题本／答案 PDF、Markdown 与 TikZ 同源 SVG 自动导出属于 #7，基线只有独立样张。没有接真实记忆或个性化。

## 验证结论

该基线 107 项后端测试和前端事件模拟通过。测试运行真实 Agno 编排并替换模型响应；没有运行真实模型或验证真机。当前没有证据表明上述能力须因 Agno 的硬限制而被砍，差异分别来自实现范围、产品选择或渲染/媒体依赖。
