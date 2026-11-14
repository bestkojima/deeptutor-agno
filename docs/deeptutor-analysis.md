# DeepTutor 能力分析与 Agno 验收基线

参考：[官方中文 Chat Workspace](https://docs.deeptutor.info/zh-cn/explore/chat-workspace/#选择一种能力)、[沉浸式阅读](https://docs.deeptutor.info/zh-cn/explore/reading/)、[v1.7.2 固定源码](https://github.com/HKUDS/DeepTutor/tree/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db)（Apache-2.0）。这里的上游行为来自静态阅读，没有把源码存在当作实际运行证明。

## 核心架构

迁移单位不是八个提示词，而是共享工具循环、权限与事件协议，加各能力的状态机、完成条件和类型化结果。Agno Agent 负责模型与工具，Workflow 编排阶段，FastAPI/SQLite 管理任务、等待确认与事件回放。前端不展示模型私有推理，只呈现阶段、工具输入/结果/错误和面向学生的解答。

| 能力 | 上游行为与源码入口 | 验收重点 |
|---|---|---|
| Chat | `deeptutor/agents/chat/agentic_pipeline.py`：通用模型工具循环，附带材料和会话上下文。 | 工具结果实际影响回答；错误不能伪装成功；明确本次可用工具。 |
| Ask Questions | `deeptutor/capabilities/ask_questions/capability.py`：设置 ask_questions_mode，强制当前所选回合首轮 ask_user，然后完成原任务。 | 先出上下文提问卡，未回答不能完成；提交答案恢复原任务；重复提交不能重复启动。 |
| Quiz | `deeptutor/agents/question/pipeline.py`：exploring→planning→quizzing；支持资料、自定义、试卷仿题及跟进；逐题事件 quiz_question_emitted，结果包含 qa_pair、metadata、成功/失败统计。 | 题量、题型、答案、解析及去重；失败或数量不足必须明确。仅模型复核不等于数学正确。 |
| Visualize | `deeptutor/visualizers/tool.py`、`registry.py`：由 submit_visualization 交付验证过的 renderer payload；普通说明不能冒充成品。Manim 是独立渲染路径。 | 验证图表结构、可渲染性；HTML/SVG 应隔离，模型生成的代码不得在主进程执行。 |
| Video Lesson | `deeptutor/agents/video_lesson/capability.py`、`runtime.py`、`narration.py`：生成→构建检查→渲染，Remotion HTML 播放产物与 TSX 源码；旁白按实际音频结果标记。 | 可播放性、字幕时间轴、旁白真实存在、失败处理。当前本地用 FFmpeg 生成 H.264 MP4 + VTT，不能视为 Remotion/TSX 等价。 |
| Immersive Reading | `deeptutor/capabilities/reading/tools.py`：复用 Chat，定位 PDF 页、EPUB 章节、媒体时间；提供阅读搜索、切换材料、查看图、定位及批注。 | 以已有摘录或带时间戳转录为依据；防止编造原文和位置；尚未接原始媒体解析、材料导航或批注时不能声称支持。 |
| Research | `deeptutor/agents/research/capability.py`、`pipeline.py`：提纲预览→编辑确认→分块检索→报告；返回 partial、失败块数和标题。 | 未确认不发起检索；分块失败如实报告；引用必须关联检索证据；精确摘录匹配不证明语义蕴含。 |
| Solve | `deeptutor/capabilities/solve/session.py`、`tools.py`：计划、步骤门禁、有限重规划，独立保存每轮状态。 | 区分计划、解法、工具证据与验证；算术回代与模型复核不是通用证明。 |

## 加入试卷模式

先把参考试卷转成可审查的蓝图，再给各题槽生成新题。蓝图固定卷名、分区、题号、题型、选项标签、分值、时长、说明及输出格式；风格描述用于约束题目措辞。蓝图不明就停在结构检查，不能推测缺失分值。结构、答案引用、客观题答案形状、规范化题干重复采用确定性校验。语义雷同、难度等价、文风是否匹配以及答案是否真的正确仍需人工抽检或独立验证。没有真实样卷时，演示只用明确标注的示例蓝图，不冒充你的考试。记忆与笔记不参与第一版。

## 验收顺序

1. 不接模型，测试所有状态、输入边界、断线重连与轨迹去重。
2. 接真 API，测试每种能力的结构化输出、异常、暂停恢复和引用。对上下文提问、逐题输出、未确认不检索做重点验收。
3. 用真实样卷核题型计数、顺序和总分，再抽检风格、难度与答案；同蓝图换 seed，检查不复用题干。
4. 单独验收可视化产物隔离、视频实际播放、TTS 和检索凭据；明确外部数据发送边界。
5. 未验证的能力、不能匹配上游的功能或依赖，不写成 1:1 已完成。
