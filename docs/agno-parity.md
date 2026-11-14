# DeepTutor → Agno：历史基线的行为对照与验收

> 本页保留 Agno 2.3.21 原型的验证记录。请以[当前实现、代码入口与限制](main-implementation.md)为现状。

基线：DeepTutor v1.7.2，固定提交 [60fb3bd](https://github.com/HKUDS/DeepTutor/tree/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db)；本项目锁定 Agno 2.3.21。对照的是功能行为，不要求同名类、同一传输协议或相同前端。已有 [流程图对照](capability-flow-comparison.md) 是原型快照。

## 判断标准

- **已接入**不等于完整复现。离线测试运行实际 Agno Workflow，模型响应替换为测试数据；这不证明模型选工具、教学内容、外部服务或真机表现。
- **未复现**要指出缺少的行为和原因。未开发、缺本地依赖、缺隔离环境都不是 Agno 硬限制。
- 本轮未证实七项上游教学能力中有一项必须因 Agno 限制舍弃。保留明确的安全与范围边界：不执行模型生成的 HTML、TSX 或 Python；不为原始音视频编造转录。

## 各项实际状态

| 能力 | DeepTutor 上游 | 当前 Agno 实现 | 尚未等价 / 暂不提供 |
| --- | --- | --- | --- |
| Chat | 共享上下文和可用工具循环，工具结果回流模型 | Workflow 中调用工具受限的 Agno Agent，再独立复核；使用请求中给出的历史与来源；计算失败给模型结构化错误，并发出失败轨迹 | 只开放已注册且经过审查的工具，未复现上游全部插件与会话上下文；不声称真实模型工具行为已验收 |
| Ask Questions | 先强制提问卡，停下来等回复；再完成原任务 | 无工具预览生成文本/单选卡 → SQLite 暂停 → 服务器验证答案并保存问答对 → 同 task ID 启动 Agno 续做；拒绝把第二张卡当任务成果 | 暂停恢复由本地任务层负责，不复制上游原生工具状态或浏览器交互；不能仅凭输出格式判断任何文字都已完成原请求 |
| Quiz | 普通题先探究/规划，模板分支跳过；每题生成→校验→修复并发事件 | 普通模式用 Agent 规划，调用方提供 `templates` 则跳过；逐题使用生成/复核 Agent，失败最多重试一次，逐题发事件；汇报成功/失败/部分成功；支持单选、多选、简答、填空 | 上游题型及字段不逐一照抄，未提供编程题执行或开放答案自动评分。结构校验和模型复核不等于答案正确证明 |
| Visualize | 可扩展目录，工具提交→校验→允许修正；独立 Manim 渲染路径 | `submit_visualization` 必须通过注册渲染；不接受仅文字说明；提供柱状、折线与线性、二次、正弦、余弦图。服务端确定性算采样点/生成 SVG；滑块可通过 `POST /api/visualize/plot` 重算而无需调用模型 | 只提供上述白名单；未开发任意几何图和交互前端。旧 HTML/SVG/Mermaid/Manim 源码不执行、不当成已渲染。Manim 沙箱和渲染器缺失，不是 Agno 限制 |
| Video Lesson | Remotion 编译、可选旁白、多轮编译和布局修复、保留可播放产物 | Agno 生成分镜 → 模型复核 → 独立渲染 Step → 受控 FFmpeg 幻灯片 MP4 和 VTT；保留可选 Edge 旁白适配，失败不发布可播放结果 | 替代实现，并非 Remotion 动画。未接 Node/Remotion 隔离执行、逐帧布局修复或回退；没有实时 Edge TTS 或真实模型验收 |
| Immersive Reading | 工具访问已授权阅读材料，按页码/时间定位，支持切页、插图与批注 | 附加段落可检索、按来源 ID 读取，精确引文可发出 `reader.located`；VTT/SRT 原始字幕可导入，保留起止时间；不读取用户文件路径或网址 | 没有原始视频/音频 ASR、扫描件 OCR、持久批注、阅读页签切换和原始媒体视图；都属于应用/媒体层 |
| Research | 提纲确认后分子题研究，各自取证，最后综合；报告可标部分失败 | SQLite 确认提纲 → Agno 规划 → 最多 6 个 `Parallel` 子题 Agent → 聚合 → 报告/复核；使用已附资料与明确启用的外部检索；不合法引文不能计作成功；全部无有效引用则不发报告 | 词法检索不是上游持久化知识库；无跨重启子题恢复或取消；在线检索未实测；逐字引文校验不证明论点受来源支持 |
| Solve | 计划、顺序完成门禁、有限重规划、步骤 checkpoint | Agno Agent 工具 `solve_plan` / `solve_finish_step` / `solve_replan`；最多 12 步/2 次重规划；不得越过未完成步骤；Agno `Loop` 最多两轮求解和复核，未通过不交付 | checkpoint 是本次运行摘要，不是跨重启恢复或上游上下文压缩；复核不是形式化证明 |
| Exam（自有） | 不是本次上游能力等价目标 | 按审阅过的蓝图出卷、结构和答案键验证；多分区离线验收 | 真实卷风格、难度、数学正确性尚未实际验证，记忆接口和个性化按已定范围延后 |

## 最小接口示例

- `POST /api/tasks` 选 `provider: "agno"` 并提供对应 `inputs`。真实模型凭据只在服务器环境配置，不交给前端。默认的 `fake` 是离线示例。
- Quiz：`inputs.quiz_count`（1–12）和 `inputs.quiz_type`；或者 `inputs.templates`（1–12 个含可选 `type` 的模板描述）。
- 图形：`POST /api/visualize/plot`，JSON `{"domain":[0,4],"samples":5,"curves":[{"function":"quadratic","parameters":{"a":1,"b":-4,"c":3}}]}`。返回计算点与服务器绘制的 SVG。
- 字幕：`POST /api/sources/captions?filename=lesson.vtt`，请求体为 UTF-8 字幕字节，不是路径。把返回 `sources` 用作阅读任务输入；此路由不做转录。
- SSE 仍用于显示工具轨迹和进度；前端只订阅新增事件，没有重做视觉界面。

## 复验

```bash
cd backend
python -m unittest discover -s tests -v
cd ..
node frontend/app.test.cjs
```

本轮实际验证：107 项 Python 测试全部通过，无跳过；前端 Node 模拟交互测试通过。使用 Agno 2.3.21 真实编排，模型调用替身；未调用真实模型、外部搜索或旁白服务。

已加入故障回归：恢复后重复出卡被拒；不合法图形先失败再提交合法图；求解未完成时模型复核点头也不能交付；研究部分失败给缺口、全部失败不生成报告；逐题生成/retry/失败统计；字幕时间戳和引文定位；普通卷结构与答案对应。详见 `backend/tests`。

上游路径：[Ask](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/ask_questions/capability.py) · [Quiz](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/question/pipeline.py) · [Solve](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/solve/tools.py) · [Visualize](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/visualizers/tool.py) · [Research](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/research/pipeline.py) · [Reading](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/reading/tools.py) · [Video](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/video_lesson/capability.py)。编排：[Agno 2.3.21 Parallel](https://github.com/agno-agi/agno/blob/v2.3.21/libs/agno/agno/workflow/parallel.py) · [Loop](https://github.com/agno-agi/agno/blob/v2.3.21/libs/agno/agno/workflow/loop.py)。
