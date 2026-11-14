# DeepTutor × Agno：能力流程对照

> 这是早期原型的流程对照快照。当前实现、离线验收与未复现项见 [Agno 行为对照](agno-parity.md)。


Capability 是 DeepTutor 面向用户的核心入口；底层真正要对齐的是运行流程：用哪些工具、在哪里等用户、怎么检查结果、失败如何恢复，以及前端看到什么事件。不只是八个提示词，也不是八套独立 API。

以 DeepTutor v1.7.2 固定源码对照当前原型。读图从左到右，不表示耗时。本次只做静态核查；42 项离线测试是已有记录，使用真实 Agno 编排、模拟模型响应，尚未做真实模型或浏览器端到端验收。

## 共用主干

DeepTutor：回合服务 → 组装上下文 → 工具循环或专用流水线 → WebSocket。Agno 原型：FastAPI → SQLite 状态与事件 → Workflow → 校验/产物 → SSE。中间有步骤与工具轨迹，数值进度主要是 10% 和 100%，不是预计耗时。

[上游回合服务](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/services/session/turns/executor.py) · [原型任务执行](../backend/app/main.py#L61-L102) · [官方能力说明](https://docs.deeptutor.info/zh-cn/explore/chat-workspace/)

## 01 · Chat

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["会话与材料组装"] --> U1["模型和获准工具往返"] --> U2["流式回答"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["传入历史与摘录"] --> P1["Agno 回答及模型复核"] --> P2["引文核对并返回"]
  end
```

**关键差异：** 白名单工具较少，未接完整附件与工作区；复核拒绝即失败。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/chat/agentic_pipeline.py) · [原型源码](../backend/app/agno_adapter.py#L164-L210)

## 02 · Ask Questions

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["当前回合首轮强制 ask_user"] --> U1["等用户回复"] --> U2["同一回合完成原请求"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["生成提问卡"] --> P1["SQLite 暂停及必填校验"] --> P2["恢复，但仍用提问指令"]
  end
```

**关键差异：** 恢复可能再次出卡而不是完成原任务。离线演示用固定卡片；这次只记录缺口，不改功能。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/ask_questions/capability.py) · [原型源码](../backend/app/main.py#L61-L92)

## 03 · Quiz

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["探索和规划；仿卷有模板则跳过"] --> U1["逐题生成、校验和必要修复"] --> U2["逐题发事件及失败统计"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["整批生成单选题"] --> P1["模型复核及选项、索引检查"] --> P2["完成后拆发逐题事件"]
  end
```

**关键差异：** 不是边生成边出题。题目结构合法不等于数学正确。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/question/pipeline.py#L515-L613) · [原型源码](../backend/app/core.py#L50-L58)

## 04 · Visualize

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["选择 renderer；Manim 走专用流水线"] --> U1["submit_visualization 校验产物"] --> U2["交画布；无有效产物则失败"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["生成图表描述"] --> P1["检查柱状/折线图数据并生成 SVG"] --> P2["前端目前仅显示结果文本"]
  end
```

**关键差异：** HTML、SVG、Mermaid、Manim 的模型源码不执行。已有几何图样张为独立制作，未接实时联动或自动出卷。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/visualizers/tool.py#L64) · [原型源码](../backend/app/visualize.py)

## 05 · Video Lesson

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["写 Remotion/TSX 课件"] --> U1["准备旁白，构建与布局检查"] --> U2["按诊断重试后交付浏览器课程"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["生成场景和时长"] --> P1["Pillow 画幻灯片、FFmpeg 合成"] --> P2["MP4 和 VTT；可选 Edge 旁白"]
  end
```

**关键差异：** 已实际生成带字幕 MP4，不是上游浏览器课件；真实旁白未联测，无同等构建修复循环。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/video_lesson/capability.py#L20-L245) · [原型源码](../backend/app/media.py#L66-L159)

## 06 · Immersive Reading

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["绑定材料和当前位置"] --> U1["先做定位预检，再用 Chat 的阅读工具"] --> U2["给带页码、章节或时间定位的回答"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["传入已有摘录与定位"] --> P1["生成讲解并复核"] --> P2["对照原句、页码、时间戳"]
  end
```

**关键差异：** 独立脚本可抽取文本层 PDF 或已有字幕；任务 API 没有原文旁读、扫描件 OCR、音视频转录、导航或批注。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/reading/tools.py) · [原型源码](../backend/app/core.py#L27-L48)

## 07 · Research

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["澄清拆题，出提纲并等确认"] --> U1["并行研究子话题与收集证据"] --> U2["分段合成引用报告，列出失败子块"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["生成提纲并暂停"] --> P1["确认后串行计划、取证、作答、复核"] --> P2["检查引用，报告工具失败"]
  end
```

**关键差异：** 原型本地用词法检索，外部检索未联测；无向量索引及研究块级并发。上游确认前不启动主研究，不代表预览绝不调工具。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/research/pipeline.py#L565-L720) · [原型源码](../backend/app/agno_adapter.py#L176-L207)

## 08 · Solve

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["共享 Chat 循环制定计划"] --> U1["当前步骤求解、门禁和检查点"] --> U2["必要时有限重规划，再答复"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["串行计划、取证、作答"] --> P1["有限算术工具与模型复核"] --> P2["拒绝则失败"]
  end
```

**关键差异：** 未实现步骤门禁或重规划。上游默认最多重规划两次、单个计划最多十二步，仍不是形式化数学证明。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/capabilities/solve/tools.py) · [原型源码](../backend/app/agno_adapter.py#L176-L194)

## 09 · Exam（扩展）

```mermaid
flowchart TB
  subgraph U["DeepTutor v1.7.2"]
    direction LR
    U0["无同名整卷模式"] --> U1["最接近 Quiz 按试卷模板仿题"] --> U2["不计入上游八项对齐"]
  end
  subgraph P["Agno 原型"]
    direction LR
    P0["样卷文本生成待审蓝图"] --> P1["按蓝图与 seed 生成、复核、去重"] --> P2["校验结构，试卷和答案分别导出"]
  end
```

**关键差异：** 目前只导 JSON 或文本；待审为提示，未强制审核凭据。未验真实文风、难度、答案或 seed 可复现；TikZ/PDF 未接入。

[上游固定源码](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/question/pipeline.py#L515-L613) · [原型源码](../backend/app/exam_blueprint.py#L130-L199)

## 先补什么

优先修 Ask Questions 的恢复闭环，再接 Exam 的几何验算 → TikZ → PDF；然后补 Solve 步骤门禁和 Quiz 逐题生成。SQLite 运行记录不是长期记忆；记忆设计留到下一轮。
