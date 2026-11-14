"""Deterministic per-run Solve spine; model/tool integration is caller-owned.

State is explicitly supplied by the caller, never a shared global session. A
checkpoint is a serializable progress snapshot, not durable storage by itself.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SolveState:
    max_replans: int = 2
    max_steps: int = 12
    analysis: str = ''
    steps: list[dict[str, Any]] = field(default_factory=list)
    replans: int = 0

    def __post_init__(self):
        if type(self.max_replans) is not int or self.max_replans < 0:
            raise ValueError('max_replans must be a nonnegative integer')
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError('max_steps must be a positive integer')

    def _validated_steps(self, steps):
        if not isinstance(steps, list) or not steps:
            raise ValueError('A nonempty steps list is required')
        result = []
        for raw in steps:
            if not isinstance(raw, dict):
                raise ValueError('Each step must contain id and goal')
            sid, goal = raw.get('id'), raw.get('goal')
            if not isinstance(sid, str) or not sid.strip() or not isinstance(goal, str) or not goal.strip():
                raise ValueError('Step id and goal must be nonempty strings')
            result.append({'id': sid.strip(), 'goal': goal.strip(), 'done': False, 'summary': ''})
        if len({s['id'] for s in result}) != len(result):
            raise ValueError('Step IDs must be unique')
        return result

    def plan(self, analysis: str, steps: list[dict]) -> dict:
        if self.steps:
            raise ValueError('Plan already set; use replan without resetting progress')
        parsed = self._validated_steps(steps)
        if len(parsed) > self.max_steps:
            raise ValueError('Step limit exceeded')
        self.analysis, self.steps = str(analysis), parsed
        return self.snapshot()

    def finish_step(self, step_id: str, summary: str) -> dict:
        pending = next((s for s in self.steps if not s['done']), None)
        if pending is None:
            raise ValueError('No pending step; plan first or all steps are complete')
        if pending['id'] != step_id:
            raise ValueError('Only the next pending step may be finished')
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError('A nonempty step summary is required')
        pending['done'], pending['summary'] = True, summary.strip()
        return {'_context_checkpoint': {
            'summary': f"[{pending['id']}] {pending['goal']} — {pending['summary']}",
            'state': self.snapshot(),
        }}

    def replan(self, reason: str, remaining_steps: list[dict]) -> dict:
        """Replace only unfinished work; completed prefix is immutable.

        Caller passes the new pending suffix, not a full replacement plan.
        Rejected requests never consume budget or mutate the current plan.
        """
        if not self.steps:
            raise ValueError('Set a plan before replanning')
        if self.complete:
            raise ValueError('Completed plan cannot be replanned')
        if self.replans >= self.max_replans:
            raise ValueError('Replan budget exhausted')
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('A nonempty replan reason is required')
        pending = self._validated_steps(remaining_steps)
        completed = [dict(s) for s in self.steps if s['done']]
        if len(completed) + len(pending) > self.max_steps:
            raise ValueError('Step limit exceeded')
        if {s['id'] for s in completed} & {s['id'] for s in pending}:
            raise ValueError('Cannot reuse completed step IDs')
        self.steps = completed + pending
        self.analysis = reason.strip()
        self.replans += 1
        return self.snapshot()

    @property
    def complete(self) -> bool:
        return bool(self.steps) and all(s['done'] for s in self.steps)

    def require_complete(self) -> dict:
        if not self.complete:
            raise ValueError('Cannot finalize until every planned step is complete')
        return self.snapshot()

    def snapshot(self) -> dict:
        return {'analysis': self.analysis, 'steps': [dict(s) for s in self.steps],
                'replans': self.replans, 'max_replans': self.max_replans,
                'max_steps': self.max_steps, 'complete': self.complete,
                'next_step_id': next((s['id'] for s in self.steps if not s['done']), None)}


def make_solve_tools(state: SolveState, emit=None) -> list:
    """Return Agno-compatible Python tools bound to one run's state.

    Errors remain errors for the framework to feed back to the model. Events
    intentionally expose only operation/state and exception type.
    """
    def invoke(name, operation, *args):
        if emit:
            emit('tool.started', {'tool': name})
        try:
            result = operation(*args)
        except ValueError:
            if emit:
                emit('tool.failed', {'tool': name, 'error_type': 'ValueError'})
            raise
        if emit:
            emit('tool.completed', {'tool': name, 'finished': sum(step['done'] for step in state.steps),
                                    'total': len(state.steps), 'replans': state.replans})
        return result

    def solve_plan(analysis: str, steps: list[dict]) -> dict:
        """Set the initial ordered plan using steps with unique id and goal."""
        return invoke('solve_plan', state.plan, analysis, steps)

    def solve_finish_step(step_id: str, summary: str) -> dict:
        """Finish only the next pending step with an educational outcome summary."""
        return invoke('solve_finish_step', state.finish_step, step_id, summary)

    def solve_replan(reason: str, remaining_steps: list[dict]) -> dict:
        """Replace pending steps only; preserve completed steps and obey budget."""
        return invoke('solve_replan', state.replan, reason, remaining_steps)

    return [solve_plan, solve_finish_step, solve_replan]
