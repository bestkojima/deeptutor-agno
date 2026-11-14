# Agno implementation and verification

Adapter targets **agno==2.3.21**, `openai`, and Pydantic 2. It uses actual `Agent`, `Workflow`, `Step`, `StepInput` and `StepOutput`, not similarly named replacements. Server secrets are read only at execution; no API calls are made at import. `OPENAI_API_KEY` enables live mode; `AGNO_MODEL` selects the server-approved OpenAI model (default gpt-4.1-mini). No secrets are required for fake mode.

API/source checked against the installed 2.3.21 wheel (`agno/agent/agent.py`, `agno/workflow/workflow.py`, `agno/workflow/step.py`, `agno/workflow/types.py`) and official documentation:
- https://docs.agno.com/workflows/overview
- https://docs.agno.com/workflows/building-workflows
- https://docs.agno.com/input-output/overview
- https://github.com/agno-agi/agno/tree/v2.3.21/libs/agno/agno

The workflow wraps sequential typed Agent calls in function Steps. Research and Solve have plan, evidence, answer and independent review agents. Other modes have answer and review agents. Each agent has a Pydantic `output_schema`; retries are disabled at Step level so failed work is not silently repeated. Application event persistence remains owned by the API layer. Interactive question-card pause/resume remains application state rather than Agno-native interrupt persistence.

Tool configuration is an explicit allowlist: `source_search` (internal alias `local_search`), `calculator`, `web_search`, `arxiv_search`. Local retrieval ranks supplied text lexically and returns bounded source records. This is basic retrieval-augmented generation, **not embedding/vector RAG**. Calculator interprets only bounded numeric AST arithmetic, never `eval`, shell or generated Python. Web/arXiv delegate to fixed-endpoint, server-opt-in retrieval adapters; returned snippets/abstracts are added to the same validated source registry. Live retrieval is not tested. No automatic personalization or cross-user memory is enabled. Agent and Workflow telemetry are disabled.

Citations are checked for source identity, exact quoted span and exact supplied page/time locator. This proves provenance, **not semantic entailment**. Model reviewer approval is not formal mathematical verification. Generated quiz/exam/visual data also requires the API's capability-specific validation/rendering; arbitrary `data` is not a rendering or execution instruction.

No live model run has been performed: model credentials were intentionally not requested. Passing deterministic tests is not evidence of live-provider parity with DeepTutor.

## Executed checks

Installed official PyPI Agno 2.3.21 and dependencies into an isolated temporary directory. Ran actual Agno `Workflow.run` with real `Step` instances and real `Agent` construction while patching only `Agent.run` to return deterministic typed outputs. The answer→review order and flattened quiz result passed. Bounded arithmetic accepted `(2+3)*4`, rejected import/call, exponentiation, subscription and boolean expressions. Exact quote/locator verification passed. This is **orchestration smoke coverage**, not a live model/provider or retrieval test; mocked agent output bypasses tool selection and API schema transport.
