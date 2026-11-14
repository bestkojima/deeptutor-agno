"""Native Agno chief -> type Teams -> designers; deterministic exam boundaries.

No model-written code is executed. A model review is not a mathematical proof.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from string import Template
from threading import RLock
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from .exam_blueprint import generation_contract, validate_generated_exam
from .exam_difficulty import difficulty_targets

MAX_SLOTS = 30
MAX_TYPES = 6
MAX_ATTEMPTS = 2
PROMPT_ROOT = Path(__file__).with_name('prompts') / 'exam'
PROMPT_ROLES = ('chief', 'type-leader', 'designer', 'blind-solver', 'reviewer')


def load_exam_prompts():
    return {role: (PROMPT_ROOT / f'{role}.md').read_text(encoding='utf-8').strip() for role in PROMPT_ROLES}

class Choice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str
    text: str

class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    section_id: str
    number: str
    stem: str = Field(min_length=1, max_length=12000)
    choices: list[Choice] = Field(max_length=12)
    answer: str | list[str] | bool
    explanation: str = Field(min_length=1, max_length=12000)

class DraftBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[Draft] = Field(max_length=MAX_SLOTS)

class LeaderAck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    completed: bool

class Solution(BaseModel):
    model_config = ConfigDict(extra='forbid')
    answer: str | list[str] | bool
    explanation: str

class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    accepted: bool
    corrections: list[str] = Field(default_factory=list, max_length=10)


def parsed(schema, value):
    return value if isinstance(value, schema) else (schema.model_validate_json(value) if isinstance(value, str) else schema.model_validate(value))


def _model(with_tools=False):
    from agno.models.openai import OpenAIChat
    model_id = os.getenv('AGNO_MODEL', 'gpt-6-luna')
    # Native leaders have delegation tools, including during a no-custom-tools request.
    return OpenAIChat(id=model_id, base_url=os.getenv('OPENAI_BASE_URL') or None,
                      reasoning_effort='none' if with_tools and model_id == 'gpt-6-luna' else None,
                      max_completion_tokens=10000, timeout=90, max_retries=0)


def _canonical(blueprint, seed, drafts):
    result = deepcopy(blueprint)
    result.update(seed=seed, answer_key=[])
    for section in result['sections']:
        section['items'] = []
        for slot in section.pop('slots'):
            key = (section['id'], slot['number'])
            draft = drafts[key]
            item = {k: v for k, v in slot.items() if k != 'source_stem'}
            item.update(stem=draft.stem, choices=[c.model_dump() for c in draft.choices])
            section['items'].append(item)
            result['answer_key'].append(dict(section_id=key[0], number=key[1], answer=draft.answer, explanation=draft.explanation))
    return result


def run_exam_teams(inputs, emit):
    from agno.agent import Agent
    from agno.team import Team
    from agno.workflow import Workflow, Step, StepOutput, Parallel, HumanReview
    contract = generation_contract(inputs['blueprint'], inputs.get('seed'))
    blueprint, seed = contract['blueprint'], contract['seed']
    targets = difficulty_targets(blueprint)
    scopes, slots = {}, {}
    for section in blueprint['sections']:
        for slot in section['slots']:
            key = (section['id'], slot['number'])
            slots[key] = {'section_id': section['id'], **deepcopy(slot), 'difficulty': targets[key]}
            scopes.setdefault(slot['type'], []).append(key)
    if len(slots) > MAX_SLOTS or len(scopes) > MAX_TYPES:
        raise ValueError('Exam Team limit: at most 30 slots and 6 types per run')
    if inputs.get('tools'):
        raise ValueError('Exam Teams use only native delegation; custom tools are not supported')
    prompts = load_exam_prompts()
    lock, drafts, accepted = RLock(), {}, {}
    failures = []
    def event(kind, data):
        with lock:
            emit(kind, data)
    def strict(name, fn):
        return Step(name=name, executor=fn, max_retries=0, human_review=HumanReview(on_error='fail'))
    def packet(keys, feedback=None):
        return {'seed': seed, 'instructions': blueprint['instructions'], 'request': inputs.get('prompt', ''),
                'slots': [slots[k] for k in keys], 'feedback': feedback or []}

    def make_team(kind, keys, attempt, feedback=None, previous_draft=None):
        team_id = 'exam-type-' + kind
        members = [Agent(id=team_id+'-'+name, name=team_id+'-'+name, role=role,
                         model=_model(), output_schema=DraftBatch, use_json_mode=True, telemetry=False,
                         instructions=[prompts['designer'],
                                       json.dumps({**packet(keys, feedback), 'previous_draft': previous_draft}, ensure_ascii=False)])
                   for name, role in [('algebra','Algebra, functions, sequences and probability question designer'),
                                      ('geometry','Geometry, vectors and trigonometry question designer')]]
        allowed = {m.id for m in members}
        async def hook(function_name, function_call, arguments):
            if function_name != 'delegate_task_to_member' or arguments.get('member_id') not in allowed:
                raise ValueError('Only direct designer delegation is permitted')
            event('exam.delegation.started', {'team': kind, 'member': arguments['member_id'], 'attempt': attempt})
            result = await function_call(**arguments)
            return result
        team = Team(id=team_id, name=team_id, model=_model(with_tools=True), members=members, telemetry=False,
                    output_schema=LeaderAck, use_json_mode=True, tool_call_limit=max(2, len(keys)), tool_hooks=[hook],
                    instructions=[Template(prompts['type-leader']).substitute(
                        kind=kind, required_slots=json.dumps([f'{section}:{number}' for section, number in keys]),
                        member_ids=', '.join(sorted(allowed))), json.dumps(packet(keys, feedback), ensure_ascii=False)])
        return team

    def member_drafts(output, team, keys):
        # The leader's textual claim is not evidence. Read genuine member run outputs.
        authorized = {m.id for m in team.members}
        found = {}
        for child in output.member_responses:
            if (getattr(child, 'agent_id', None) not in authorized
                    or getattr(child, 'team_id', None) not in (None, team.id)
                    or child.parent_run_id != output.run_id):
                raise ValueError('Unexpected designer response in Team output')
            event('exam.delegation.completed', {'team': team.id, 'member': child.agent_id})
            for item in parsed(DraftBatch, child.content).items:
                key = (item.section_id, item.number)
                if key not in keys or key in found:
                    raise ValueError('Designer returned extra or duplicate slot')
                found[key] = item
        if set(found) != set(keys):
            raise ValueError('Team did not actually delegate every slot')
        return found

    async def draft_all():
        groups = [make_team(kind, keys, 1) for kind, keys in scopes.items()]
        async def chief_hook(function_name, function_call, arguments):
            if function_name != 'delegate_task_to_members':
                raise ValueError('Chief must delegate to all direct type Teams')
            event('exam.delegation.started', {'team': 'chief', 'members': [t.id for t in groups]})
            result = await function_call(**arguments)
            return result
        chief = Team(id='exam-chief', name='exam-chief', model=_model(with_tools=True), members=groups,
                     delegate_to_all_members=True, tool_call_limit=1, tool_hooks=[chief_hook],
                     telemetry=False, output_schema=LeaderAck, use_json_mode=True,
                     instructions=[prompts['chief']])
        for kind, keys in scopes.items():
            event('exam.team.started', {'team': kind, 'total': len(keys)})
        response = await chief.arun(json.dumps(packet(list(slots)), ensure_ascii=False))
        event('exam.delegation.completed', {'team': 'chief', 'members': [r.team_id for r in response.member_responses]})
        children = {r.team_id: r for r in response.member_responses}
        if len(children) != len(groups) or len(response.member_responses) != len(groups):
            raise ValueError('Chief failed to delegate exactly once to each type Team')
        for group, (kind, keys) in zip(groups, scopes.items()):
            if group.id not in children or children[group.id].parent_run_id != response.run_id:
                raise ValueError('Chief omitted a type Team')
            drafts.update(member_drafts(children[group.id], group, keys))

    def generate(step_input):
        event('step.started', {'name': 'exam_chief_delegation', 'engine': 'agno-team'})
        asyncio.run(draft_all())
        return StepOutput(content={'drafted': len(drafts)})

    def validate_slot(key, draft):
        # Reuse the full canonical contract, narrowed to one slot without changing
        # its expected properties, rather than maintaining a weaker parallel schema.
        if slots[key]['type'] == 'multiple_choice' and (not isinstance(draft.answer, list) or len(draft.answer) < 2):
            raise ValueError('Multiple-choice Team slots require at least two declared correct labels')
        scope = deepcopy(blueprint)
        original = next(s for s in scope['sections'] if s['id'] == key[0])
        original['slots'] = [s for s in original['slots'] if s['number'] == key[1]]
        original['duration_minutes'] = None
        scope['sections'] = [original]
        scope['total_points'] = original['slots'][0]['points']
        validate_generated_exam(scope, _canonical(scope, seed, {key: draft}), inputs.get('prior_stems', ()))

    async def assess(key, draft):
        shared = {'slot': slots[key], 'stem': draft.stem, 'choices': [c.model_dump() for c in draft.choices]}
        solver = Agent(name='exam_blind_solver', model=_model(), output_schema=Solution, use_json_mode=True, telemetry=False,
                       instructions=[prompts['blind-solver']])
        solution = parsed(Solution, (await solver.arun(json.dumps(shared, ensure_ascii=False))).content)
        reviewer = Agent(name='exam_slot_reviewer', model=_model(), output_schema=Decision, use_json_mode=True, telemetry=False,
                         instructions=[prompts['reviewer']])
        return parsed(Decision, (await reviewer.arun(json.dumps({**shared, 'author': draft.model_dump(), 'independent_solution': solution.model_dump()}, ensure_ascii=False))).content)

    def review_type(kind, keys):
        def executor(step_input):
            for key in keys:
                item = drafts[key]
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    event('exam.slot.started', {'team': kind, 'section_id': key[0], 'number': key[1], 'attempt': attempt})
                    try:
                        validate_slot(key, item)
                        decision = asyncio.run(assess(key, item))
                        feedback = decision.corrections or ['Independent reviewer did not accept this slot.']
                        ok = decision.accepted
                    except (ValueError, TypeError) as exc:
                        ok, feedback = False, ['Slot contract or response schema invalid; comply with the provided schema.']
                    except Exception:
                        # Do not burn budget repairing a network/provider outage.
                        ok, feedback = False, ['Provider failed; this slot remains unresolved.']
                        attempt = MAX_ATTEMPTS
                    if ok:
                        with lock:
                            accepted[key] = item
                            count = len(accepted)
                            event('exam.slot.accepted', {'team': kind, 'section_id': key[0], 'number': key[1], 'attempt': attempt})
                            event('progress', {'percent': round(count/len(slots)*95), 'message': f'Exam reviewed {count}/{len(slots)}', 'completed': count, 'total': len(slots)})
                        break
                    if attempt >= MAX_ATTEMPTS:
                        with lock:
                            failures.append(key)
                        event('exam.slot.failed', {'team': kind, 'section_id': key[0], 'number': key[1]})
                        break
                    event('exam.slot.retrying', {'team': kind, 'section_id': key[0], 'number': key[1], 'next_attempt': attempt+1})
                    async def repair():
                        team = make_team(kind, [key], attempt+1, feedback, item.model_dump())
                        reply = await team.arun(json.dumps({**packet([key], feedback), 'previous_draft': item.model_dump()}, ensure_ascii=False))
                        return member_drafts(reply, team, [key])[key]
                    try:
                        item = asyncio.run(repair())
                    except Exception:
                        with lock:
                            failures.append(key)
                        event('exam.slot.failed', {'team': kind, 'section_id': key[0], 'number': key[1]})
                        break
            event('exam.team.completed', {'team': kind, 'accepted': sum(k in accepted for k in keys), 'total': len(keys)})
            return StepOutput(content={'team': kind})
        return strict('exam_review_'+kind, executor)

    def merge(step_input):
        if failures or set(accepted) != set(slots):
            raise ValueError('Exam has unresolved slots; no complete paper will be published')
        result = _canonical(blueprint, seed, accepted)
        validate_generated_exam(blueprint, result, inputs.get('prior_stems', ()))
        return StepOutput(content=result)

    workflow = Workflow(name='DeepTutor-exam-teams', telemetry=False, steps=[
        strict('exam_chief_delegation', generate),
        Parallel(*(review_type(kind, keys) for kind, keys in scopes.items()), name='exam_type_review_parallel'),
        strict('exam_assemble', merge)])
    response = workflow.run(input={'slot_count': len(slots)})
    if not isinstance(response.content, dict) or 'answer_key' not in response.content:
        raise ValueError('Exam Team workflow failed; no paper published')
    return validate_generated_exam(blueprint, response.content, inputs.get('prior_stems', ()))
