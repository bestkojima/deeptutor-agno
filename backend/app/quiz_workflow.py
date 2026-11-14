"""Bounded sequential issuance with structural checks and caller-owned review.

No provider/network dependencies. Review is evidence from a callback, not proof
of answer correctness. Failed items never enter accepted context.
"""
from copy import deepcopy
from .core import validate_quiz


def generate_quiz(targets, generate, review, emit):
    """Generate each target, retry once after rejection, and emit its outcome.

    generate(target, accepted_items, corrections) -> item dict
    review(item) -> {accepted: bool, corrections: list[str]}
    emit(event_name, payload) persists events and must raise on storage failure.

    Inputs and callback context are defensively copied. Exceptions from generation
    or review become explicit per-item failures; event-storage failures propagate.
    Targets are bounded descriptors (dicts); an optional type constrains item type.
    """
    if not isinstance(targets, list) or not 1 <= len(targets) <= 50:
        raise ValueError('Quiz requires 1–50 planned targets')
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError('Each target must be an object')
        if 'type' in target and target['type'] not in ('single_choice', 'multiple_choice', 'short_answer', 'fill_blank'):
            raise ValueError('Unsupported planned quiz type')
    if not all(callable(callback) for callback in (generate, review, emit)):
        raise ValueError('Quiz callbacks must be callable')
    accepted, outcomes, stems, ids = [], [], set(), set()
    for position, original in enumerate(deepcopy(targets), 1):
        corrections = []
        outcome = None
        for attempt in (1, 2):
            emit('quiz.question.started', {'position':position,'attempt':attempt,'target':deepcopy(original)})
            try:
                item = generate(deepcopy(original), deepcopy(accepted), list(corrections))
                validate_quiz({'items':[item]})
                if original.get('type') and item.get('type','single_choice') != original['type']:
                    raise ValueError('Generated type differs from planned type')
                stem = ' '.join(item['question'].split()).casefold()
                if stem in stems:
                    raise ValueError('Generated question repeats an accepted question')
                item_id = item.get('id')
                identity = item_id.strip().casefold() if item_id is not None else None
                if identity is not None and identity in ids:
                    raise ValueError('Generated item ID repeats an accepted ID')
                verdict = review(deepcopy(item))
                if not isinstance(verdict,dict) or type(verdict.get('accepted')) is not bool:
                    raise ValueError('Reviewer must return a boolean accepted field')
                notes = verdict.get('corrections', [])
                if not isinstance(notes,list) or len(notes)>20 or any(not isinstance(note,str) or not note.strip() or len(note)>2000 for note in notes):
                    raise ValueError('Reviewer corrections must be bounded nonempty text')
                if not verdict['accepted']:
                    corrections = list(notes) or ['Reviewer rejected the item without specific corrections']
                else:
                    # Snapshot before exposing item to any downstream callback.
                    accepted.append(deepcopy(item)); stems.add(stem)
                    if identity is not None: ids.add(identity)
                    outcome = {'position':position,'status':'success','attempts':attempt,'review':deepcopy(verdict)}
            except Exception as exc:
                # Do not serialize exception messages: providers may include
                # credentials, raw requests, or private source text in errors.
                corrections = [f'Generation/validation/review failed ({type(exc).__name__}); regenerate a structurally valid item and verify the answer.']
            if outcome is not None:
                emit('quiz.question.emitted', {'position':position,'attempt':attempt,'item':deepcopy(accepted[-1]),'review':deepcopy(outcome['review'])})
                break
            emit('quiz.question.rejected', {'position':position,'attempt':attempt,'corrections':list(corrections),'will_retry':attempt==1})
        if outcome is None:
            outcome = {'position':position,'status':'failed','attempts':2,'corrections':list(corrections)}
            emit('quiz.question.failed',deepcopy(outcome))
        outcomes.append(outcome)
    successful = len(accepted)
    status = 'completed' if successful == len(targets) else ('partial' if successful else 'failed')
    summary = {'status':status,'requested':len(targets),'successful':successful,'failed':len(targets)-successful,'outcomes':outcomes,'semantic_correctness':'review_callback_only_not_proven'}
    emit('quiz.completed',deepcopy(summary))
    return {'kind':'quiz','items':accepted,'quiz_status':summary}
