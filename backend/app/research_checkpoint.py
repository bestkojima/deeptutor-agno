"""SQLite research checkpoints: no model configuration or credentials are stored.

Only explicitly confirmed research may create this store. The server owns task
identity, launch leases and resume authorization. Retry policy: on explicit
resume, reuse validated completed branches and retry other branches once. Keep
prior verified partial evidence if the retry yields no cited evidence.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from copy import deepcopy
from .research_workflow import split_research_plan, _normalize_evidence


class ResearchCheckpointStore:
    def __init__(self, database, task_id: str, inputs: dict):
        if not isinstance(inputs.get('confirmed_outline'), (str, list)) or not inputs['confirmed_outline']:
            raise ValueError('Only confirmed research is checkpoint eligible')
        if not isinstance(task_id, str) or not task_id:
            raise ValueError('Checkpoint requires the original task ID')
        self.database, self.task_id = str(database), task_id
        # Binding prevents accidental reuse after changed inputs; no raw request saved.
        self.fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS research_checkpoints (task_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, plan TEXT, branches TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO research_checkpoints VALUES (?, ?, NULL, ?)', (task_id, self.fingerprint, '{}'))
            self._row(db)

    def _connect(self):
        return sqlite3.connect(self.database, timeout=30)

    def _row(self, db):
        row = db.execute('SELECT fingerprint, plan, branches FROM research_checkpoints WHERE task_id=?', (self.task_id,)).fetchone()
        if row is None or row[0] != self.fingerprint:
            raise ValueError('Research checkpoint inputs differ from the confirmed task')
        return row

    def load(self):
        with self._connect() as db:
            _, plan, branches = self._row(db)
        result = {'plan': json.loads(plan) if plan else None, 'branches': json.loads(branches)}
        if result['plan'] is not None:
            scopes = {s['name']: s['task'] for s in split_research_plan(result['plan'])}
            if not isinstance(result['branches'], dict) or len(result['branches']) > len(scopes):
                raise ValueError('Malformed research branch checkpoint')
            for name, record in result['branches'].items():
                if not isinstance(record, dict) or name != record.get('name') or scopes.get(name) != record.get('task') or record.get('status') not in ('completed', 'partial', 'failed'):
                    raise ValueError('Checkpoint branch does not match the saved plan')
        elif result['branches']:
            raise ValueError('Research branches require a saved plan')
        return result

    def save_plan(self, plan):
        split_research_plan(plan)
        clean = {'tasks': list(plan['tasks'])}
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _, prior, _ = self._row(db)
            if prior is not None and json.loads(prior) != clean:
                raise ValueError('A checkpointed plan cannot change during resume')
            db.execute('UPDATE research_checkpoints SET plan=? WHERE task_id=?', (json.dumps(clean), self.task_id))

    def save_branch(self, record, sources):
        # Whitelist persisted fields, excluding arbitrary model-produced data.
        clean = {k: deepcopy(record[k]) for k in ('name', 'task', 'status', 'gaps')}
        clean['evidence'] = None
        clean_sources = []
        if record.get('evidence') is not None:
            evidence = _normalize_evidence(record['evidence'])
            evidence.pop('gaps')
            indexed = {str(s['id']): s for s in sources}
            ids = list(dict.fromkeys(c['source_id'] for c in evidence['citations']))
            for citation in evidence['citations']:
                source = indexed.get(citation['source_id'])
                if source is None or citation['quote'] not in source['text']:
                    raise ValueError('Cannot checkpoint unverified evidence')
                for key in ('page', 'start_seconds', 'end_seconds'):
                    if key in citation and citation[key] != source.get(key):
                        raise ValueError('Cannot checkpoint a mismatched locator')
            clean['evidence'] = evidence
            clean_sources = [{k: indexed[sid][k] for k in ('id', 'text', 'title', 'url', 'page', 'start_seconds', 'end_seconds') if k in indexed[sid]} for sid in ids]
        clean['sources'] = clean_sources
        if record.get('status') == 'failed':
            clean['error_type'] = 'EvidenceBranchFailed'
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _, plan, branches_json = self._row(db)
            if plan is None:
                raise ValueError('Save the research plan before any branch')
            scopes = {s['name']: s['task'] for s in split_research_plan(json.loads(plan))}
            if scopes.get(clean['name']) != clean['task']:
                raise ValueError('Checkpoint branch does not match plan')
            branches = json.loads(branches_json)
            branches[clean['name']] = clean
            db.execute('UPDATE research_checkpoints SET branches=? WHERE task_id=?', (json.dumps(branches, ensure_ascii=False), self.task_id))
