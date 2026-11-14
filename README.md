# Agno Tutor Workbench (independent implementation)

当前复现范围与限制：[DeepTutor → Agno 行为对照与验收](docs/agno-parity.md)。

LaTeX 样式示例：[2026 新课标Ⅰ卷体例](examples/latex-gaokao-i-2026/)。该样式可单独编译；自动出卷接入 LaTeX、PDF 与 Markdown/SVG 由 [Exam 工单 #7](https://github.com/bestkojima/deeptutor-agno/issues/7) 跟踪。


A local, single-user educational workflow prototype inspired by DeepTutor. This is **not a verified 1:1 DeepTutor replacement**. No upstream code is copied. Upstream: https://github.com/HKUDS/DeepTutor (Apache-2.0); official capability reference: https://docs.deeptutor.info/zh-cn/explore/chat-workspace .

## Run

Python 3.11+ recommended. Create a virtual environment, then:

```sh
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Visit http://127.0.0.1:8000 . Default provider is explicitly labeled deterministic offline fixtures. It does not produce real teaching content and does not call an external model. Configure an OpenAI key on the server and select Agno for real model execution; never paste keys into source text or the UI. See `docs/AGNO.md` for model configuration and verified framework APIs.

```sh
cd backend
python -m unittest discover -s tests -v
```

FFmpeg must be installed for MP4 lessons. Pillow is required. Optional Edge TTS needs an installed `edge-tts` package and explicit operator opt-in; it transmits lesson text to the speech service. The local renderer uses Python + FFmpeg, **not upstream Remotion/Node**, so Node 22+/npm feature parity is not claimed.

## Implemented and limited

- SQLite-backed run and tool journal, progress/errors, SSE replay with Last-Event-ID, interactive question cards and durable resume. A restart marks unfinished active runs failed rather than repeating external calls. Paused runs remain resumable.
- Chat routes to a real structured Agno workflow when configured. Tools are an explicit restricted allowlist, not arbitrary Python/shell.
- Ask Questions pauses the run for contextual answers. Offline cards are deterministic; the Agno path creates contextual cards. Resume retains the ask-card instructions, so completing the original request is a known gap.
- Quiz validates answer-index bounds, distinct options and explanations. This is structural validation, not a proof of pedagogical correctness.
- Visualize generates structured chart artifacts including trusted chart SVG strings; the frontend currently displays results as text. HTML/SVG/Mermaid payloads must be shown as inert text unless a separately isolated renderer is added. Manim execution is disabled. No generated code is executed.
- Video lessons create actual MP4 slides and VTT captions with optional configured TTS. This differs from upstream HTML/TSX lesson playback.
- Immersive Reading uses user-supplied extracted text or timestamped transcripts. Exact quote matching preserves supplied page/time coordinates. PDF parsing, OCR, diarization and raw audio/video transcription are **not implemented**.
- Research has an outline confirmation checkpoint, supplied-source retrieval and optional explicitly enabled arXiv/web adapters. No exhaustive research quality or parity claim. Retrieval/model availability failures are visible.
- Solve is multi-step in real mode, with a restricted arithmetic calculator. Fake mode only evaluates arithmetic. Repeating arithmetic is not an independent mathematical proof.
- Exam requires a reviewed structured blueprint. It preserves structural order/type/counts/points/styles and checks repeats. The fake fixture is deliberately marked as such. Automated extraction from arbitrary exam PDFs and semantic difficulty equivalence remain unverified.
- No personalization or long-term memory is enabled; run persistence is operational history, not user profiling.

## Security and deployment

Bind only to `127.0.0.1`. There is no account/authentication layer or multi-tenant isolation. Do not expose directly to a network. Browser UI uses text nodes for untrusted model content, no `eval`/generated shell execution and no same-origin untrusted HTML. Media resolution restricts filenames and artifact IDs. SQLite stores supplied source text and answers locally. Production use requires authenticated access, retention policy, resource limits and a separate origin/sandbox for active artifacts.

## API

`POST /api/tasks` → 202 `{id,status}`:

```json
{"capability":"solve","provider":"fake","inputs":{"prompt":"(2 + 3) * 4","tools":["calculator"]}}
```

Capability IDs: `chat`, `ask_questions`, `quiz`, `visualize`, `video_lesson`, `immersive_reading`, `research`, `solve`, `exam`.

`GET /api/tasks/{id}` returns status/result/error. `GET /api/tasks/{id}/events` is SSE with durable numeric IDs; each data object is `{id,task_id,type,data,created_at}`. Events include `run.created`, `run.started`, `step.started`, `tool.started`, `tool.completed`, `tool.failed`, `progress`, `question`, `result`, `error`, `run.resumed`, `run.completed`. Reconnect using `Last-Event-ID` or `?after=N`.

`POST /api/tasks/{id}/resume` accepts `{"answers":{"goal":"confirmed or revised goal","attempt":"optional"}}`. Only paused tasks can resume; duplicate resume returns 409. `GET /api/capabilities` reports provider readiness and limitations. `GET /api/media/{id}/{filename}` serves allowlisted generated media.

Sources are `inputs.sources: [{id,title,text,page?,start_seconds?,end_seconds?}]`. Source coordinates describe the supplied excerpt; they are not inferred from raw documents. Exam blueprint example: `backend/app/exam_blueprint.py:EXAMPLE_BLUEPRINT`.

## 中文使用补充

- [八项能力与 Exam 的泳道流程对照](docs/capability-flow-comparison.md)。
- [官方功能分析](docs/deeptutor-analysis.md) 与 [验收、差异及配置](docs/验收与差异.md)。
- 试卷 Demo 请求见 examples/exam-request.json；有真 API 后可通过 POST /api/exam/blueprint 从样卷文本生成待审核蓝图。
- 测试：在 backend 执行 python -m unittest discover -s tests -v，在根目录执行 node frontend/app.test.cjs。
