"""Bounded research fan-out using Agno's real Parallel/Step objects.

No model, credentials or network client lives here. The adapter supplies a
thread-safe, timeout-bounded ``run_branch(name, task)`` callback and owns source
retrieval, provenance verification and the final synthesis/review. Branches must
not mutate the adapter's shared plan/output dictionaries.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from threading import Lock
from typing import Any, Callable

MAX_BRANCHES = 6
MAX_TASK_CHARS = 4000
MAX_BRANCH_TEXT_CHARS = 24000
MAX_CITATIONS_PER_BRANCH = 40


def split_research_plan(plan_context: dict[str, Any]) -> list[dict[str, str]]:
    """Assign stable names to distinct tasks without silently dropping scope.

    Accept a Plan dictionary, or the adapter context containing outputs.plan.
    A confirmed outline is a fallback only when no generated tasks exist. Large
    plans fail before any provider calls rather than hiding omitted sections.
    """
    if not isinstance(plan_context, dict):
        raise ValueError('Research plan context must be an object')
    plan = plan_context.get('outputs', {}).get('plan', plan_context)
    if hasattr(plan, 'model_dump'):
        plan = plan.model_dump()
    if not isinstance(plan, dict):
        raise ValueError('Research plan must be an object')
    tasks = plan.get('tasks')
    if tasks is None:
        outline = plan_context.get('request', {}).get('confirmed_outline')
        if isinstance(outline, str):
            tasks = [line.strip() for line in outline.splitlines() if line.strip()]
        else:
            tasks = outline
    if not isinstance(tasks, list) or not tasks or len(tasks) > MAX_BRANCHES:
        raise ValueError('Research requires between one and six scoped tasks')
    unique: list[str] = []
    for task in tasks:
        if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
            raise ValueError('Research tasks must be nonempty strings of at most 4000 characters')
        normalized = task.strip()
        if normalized not in unique:
            unique.append(normalized)
    return [{'name': f'research_evidence_{i:02d}', 'task': task}
            for i, task in enumerate(unique, 1)]


def _normalize_evidence(value: Any) -> dict[str, Any]:
    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    if not isinstance(value, dict):
        raise ValueError('Branch output must be a TutorOutput object')
    text = value.get('text')
    citations = value.get('citations', [])
    limitations = value.get('limitations', [])
    data = value.get('data', {})
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_BRANCH_TEXT_CHARS:
        raise ValueError('Branch evidence text is empty or over its bound')
    if not isinstance(citations, list) or len(citations) > MAX_CITATIONS_PER_BRANCH:
        raise ValueError('Branch citation limit exceeded')
    for citation in citations:
        if not isinstance(citation, dict) or not isinstance(citation.get('source_id'), str) or not citation['source_id'] or not isinstance(citation.get('quote'), str) or not citation['quote'] or len(citation['quote']) > 12000:
            raise ValueError('Malformed branch citation')
        if set(citation) - {'source_id', 'quote', 'page', 'start_seconds', 'end_seconds'}:
            raise ValueError('Unexpected branch citation fields')
        page = citation.get('page')
        if page is not None and (type(page) is not int or page < 1):
            raise ValueError('Malformed citation page')
        for key in ('start_seconds', 'end_seconds'):
            locator = citation.get(key)
            if locator is not None and (type(locator) not in (int, float) or not math.isfinite(locator) or locator < 0):
                raise ValueError('Malformed citation timestamp')
    if not isinstance(limitations, list) or len(limitations) > 40 or any(not isinstance(x, str) or len(x) > 4000 for x in limitations):
        raise ValueError('Malformed branch limitations')
    if not isinstance(data, dict):
        raise ValueError('Malformed branch data')
    # Explicit gaps can be provided by the branch in addition to limitations.
    gaps = data.get('gaps', [])
    if not isinstance(gaps, list) or len(gaps) > 40 or any(not isinstance(x, str) or len(x) > 4000 for x in gaps):
        raise ValueError('Malformed branch gaps')
    # Retain only bounded evidence fields, not arbitrary model-produced data.
    return deepcopy({'text': text, 'citations': citations, 'limitations': limitations,
                     'gaps': gaps})


def research_evidence_stage(
    plan_context: dict[str, Any],
    run_branch: Callable[[str, str], dict[str, Any]],
    emit: Callable[[str, dict[str, Any]], None],
    *, completed_branches: dict[str, dict[str, Any]] | None = None,
    checkpoint_branch: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run at most six evidence workers once each and aggregate in plan order.

    Each failure is a visible gap, not a fabricated success or automatic retry.
    A result with all_failed=True must not be presented as completed research.
    Ordering of live started/completed events reflects actual concurrency;
    aggregate branches/citations/gaps always follow the original plan order.
    """
    scopes = split_research_plan(plan_context)
    from agno.workflow import Parallel, Step, StepInput, StepOutput

    lock = Lock()
    records: dict[str, dict[str, Any]] = {}
    completed_branches = completed_branches or {}
    checkpoint_errors = []

    def event(kind: str, data: dict[str, Any]) -> None:
        # The caller may persist events in a store that requires serialization.
        with lock:
            emit(kind, data)

    def make_step(scope: dict[str, str]):
        name, task = scope['name'], scope['task']

        def executor(step_input: StepInput) -> StepOutput:
            cached = completed_branches.get(name)
            usable_cache = (cached is not None and cached.get('task') == task
                            and (cached.get('evidence') or {}).get('citations'))
            if usable_cache and cached.get('status') == 'completed':
                record = deepcopy(cached)
                with lock:
                    records[name] = record
                event('research.checkpoint.reused', {'name': name, 'status': record['status']})
                return StepOutput(content=record)
            event('step.started', {'name': name, 'engine': 'agno', 'task': task})
            try:
                evidence = _normalize_evidence(run_branch(name, task))
                gaps = list(dict.fromkeys(evidence.pop('gaps') + evidence['limitations']))
                if not evidence['citations']:
                    gaps.append('No cited evidence returned for this task; claims remain unverified.')
                record = {**scope, 'status': 'partial' if gaps else 'completed',
                          'evidence': evidence, 'gaps': gaps}
            except Exception as exc:
                # Exception text may contain credentials, URLs or provider bodies.
                record = {**scope, 'status': 'failed', 'error_type': type(exc).__name__,
                          'evidence': None, 'gaps': ['Evidence branch failed; this task is unresolved.']}
            if (usable_cache and cached.get('status') == 'partial'
                    and not (record.get('evidence') or {}).get('citations')):
                record = {**deepcopy(cached),
                          'gaps': list(dict.fromkeys(cached['gaps'] +
                              ['Resume did not obtain new cited evidence; previous partial evidence retained.']))}
                event('research.checkpoint.retained', {'name': name, 'status': 'partial'})
            if checkpoint_branch is not None:
                try:
                    checkpoint_branch(record)
                except Exception:
                    with lock:
                        checkpoint_errors.append(name)
                    return StepOutput(content={'checkpoint_failed': name})
            with lock:
                records[name] = record
            event('step.failed' if record['status'] == 'failed' else 'progress',
                  {'name': name, 'step': name, 'status': record['status'],
                   **({'error_type': record['error_type']} if 'error_type' in record else {})})
            # Partial/failure is represented as data so healthy siblings finish.
            return StepOutput(content=record)

        return Step(name=name, executor=executor, max_retries=0)

    event('research.parallel.started', {'branches': len(scopes), 'engine': 'agno', 'max_branches': MAX_BRANCHES})
    Parallel(*(make_step(scope) for scope in scopes), name='research_evidence_parallel').execute(
        StepInput(input={'tasks': deepcopy(scopes)}))

    if checkpoint_errors:
        raise RuntimeError('Research checkpoint persistence failed; report withheld')

    branches, citations, gaps, paragraphs = [], [], [], []
    seen_citations: set[str] = set()
    for scope in scopes:
        record = records.get(scope['name'])
        if record is None:
            record = {**scope, 'status': 'failed', 'error_type': 'MissingBranchOutput',
                      'evidence': None, 'gaps': ['Evidence branch produced no output; this task is unresolved.']}
        branches.append(record)
        for gap in record['gaps']:
            gaps.append({'branch': scope['name'], 'task': scope['task'], 'reason': gap})
        if record['evidence'] is not None:
            paragraphs.append(scope['task'] + '\n' + record['evidence']['text'])
            for citation in record['evidence']['citations']:
                fingerprint = json.dumps(citation, sort_keys=True, ensure_ascii=False)
                if fingerprint not in seen_citations:
                    seen_citations.add(fingerprint)
                    citations.append(citation)
    failed = [branch['name'] for branch in branches if branch['status'] == 'failed']
    result = {
        'text': '\n\n'.join(paragraphs) or 'No research evidence was obtained. All planned tasks remain unresolved.',
        'citations': citations,
        'data': {'branches': branches, 'gaps': gaps, 'partial': bool(gaps),
                 'failed_branches': failed, 'all_failed': len(failed) == len(branches),
                 'branch_count': len(branches), 'orchestration': 'agno.Parallel'},
        'limitations': [f"{gap['branch']}: {gap['reason']}" for gap in gaps],
    }
    event('research.parallel.completed', {'branches': len(branches), 'failed_branches': failed,
                                         'partial': bool(gaps)})
    return result
