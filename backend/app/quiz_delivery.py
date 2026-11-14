"""Student delivery boundary and deterministic objective scoring.

Private keys live in separate SQLite records, never in public event payloads.
All public quiz event bodies use allowlists: arbitrary model/tool/review prose is
not a student trace. Keys and explanations are exposed only for submitted items.
This does not determine whether generated question wording leaks its own answer.
"""
from copy import deepcopy
import hashlib
import json
from .core import validate_quiz


class QuizSubmissionError(ValueError):
    def __init__(self,message,status_code=422):
        super().__init__(message);self.status_code=status_code


def init_quiz_db(db):
    db.execute('CREATE TABLE IF NOT EXISTS quiz_delivery_items (task_id TEXT NOT NULL,item_id TEXT NOT NULL,position INTEGER NOT NULL,private_json TEXT NOT NULL,fingerprint TEXT NOT NULL,PRIMARY KEY(task_id,item_id),UNIQUE(task_id,fingerprint))')
    db.execute('CREATE TABLE IF NOT EXISTS quiz_delivery_submissions (task_id TEXT NOT NULL,item_id TEXT NOT NULL,answer_json TEXT NOT NULL,feedback_json TEXT NOT NULL,PRIMARY KEY(task_id,item_id))')
    db.execute('CREATE TABLE IF NOT EXISTS quiz_delivery_meta (task_id TEXT PRIMARY KEY,summary_json TEXT NOT NULL)')


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def _fingerprint(item):return hashlib.sha256(_json(item).encode()).hexdigest()
def _rows(db,task_id):return db.execute('SELECT * FROM quiz_delivery_items WHERE task_id=? ORDER BY position,item_id',(task_id,)).fetchall()
def _small_int(value):return type(value) is int and 0<=value<=1000


def _record(db,task_id,item,position=None):
    validate_quiz({'items':[item]})
    fingerprint=_fingerprint(item)
    found=db.execute('SELECT * FROM quiz_delivery_items WHERE task_id=? AND fingerprint=?',(task_id,fingerprint)).fetchone()
    if found:return found
    rows=_rows(db,task_id)
    if len(rows)>=50:raise ValueError('Quiz delivery item limit exceeded')
    if not _small_int(position) or position==0:position=max((row['position'] for row in rows),default=0)+1
    identity=f'q{position}'
    if any(row['item_id']==identity for row in rows):raise ValueError('Conflicting quiz issuance position')
    db.execute('INSERT INTO quiz_delivery_items VALUES(?,?,?,?,?)',(task_id,identity,position,_json(item),fingerprint))
    return db.execute('SELECT * FROM quiz_delivery_items WHERE task_id=? AND item_id=?',(task_id,identity)).fetchone()


def _public_item(item,identity):
    kind=item.get('type','single_choice')
    if kind not in ('single_choice','multiple_choice','short_answer','fill_blank') or not isinstance(item.get('question'),str):
        raise ValueError('Invalid public item shape')
    if kind in ('single_choice','multiple_choice') and (not isinstance(item.get('options'),list) or any(not isinstance(option,str) for option in item['options'])):
        raise ValueError('Invalid public options')
    if kind=='fill_blank' and (not isinstance(item.get('blanks'),list) or any(not isinstance(blank,dict) or not isinstance(blank.get('id'),str) for blank in item['blanks'])):
        raise ValueError('Invalid public blanks')
    public={'id':identity,'type':kind,'question':item['question'],'scoring':'objective' if kind in ('single_choice','multiple_choice') else 'manual_review'}
    if kind in ('single_choice','multiple_choice'):public['options']=deepcopy(item['options'])
    if kind=='fill_blank':public['blanks']=[{'id':blank['id']} for blank in item['blanks']]
    return public


def _summary(db,task_id):
    row=db.execute('SELECT summary_json FROM quiz_delivery_meta WHERE task_id=?',(task_id,)).fetchone()
    value=json.loads(row['summary_json']) if row else {}
    value['successful']=len(_rows(db,task_id))
    return value


def _safe_summary(data):
    if not isinstance(data,dict):return {}
    result={key:data[key] for key in ('requested','successful','failed') if _small_int(data.get(key))}
    if data.get('status') in ('completed','partial','failed','running'):result['status']=data['status']
    return result


def _student_result(db,task_id,include_feedback=True):
    result={'kind':'quiz','items':[_public_item(json.loads(row['private_json']),row['item_id']) for row in _rows(db,task_id)],'quiz_status':_summary(db,task_id)}
    if include_feedback:result.update(_feedback(db,task_id))
    return result


def capture_quiz_event(db,task_id,kind,data):
    """Call inside the same transaction as event insertion; returns public data."""
    if isinstance(data,dict):
        if kind in ('quiz.question.emitted','quiz.question'):
            item=data.get('item') if kind=='quiz.question.emitted' else data
            _record(db,task_id,item,data.get('position'))
        elif kind=='result' and isinstance(data.get('items'),list):
            for item in data['items']:_record(db,task_id,item)
        if kind in ('quiz.completed','result'):
            summary=_safe_summary(data.get('quiz_status',data))
            db.execute('INSERT INTO quiz_delivery_meta VALUES(?,?) ON CONFLICT(task_id) DO UPDATE SET summary_json=excluded.summary_json',(task_id,_json(summary)))
    return public_quiz_event(db,task_id,kind,data)


def public_quiz_event(db,task_id,kind,data):
    """Apply on SSE reads too, protecting older unsanitized journal rows."""
    data=data if isinstance(data,dict) else {}
    numbers={key:data[key] for key in ('position','attempt','percent') if _small_int(data.get(key))}
    if kind in ('quiz.question.emitted','quiz.question'):
        item=data.get('item') if kind=='quiz.question.emitted' else data
        if not isinstance(item,dict):return {'message':'Quiz item unavailable.'}
        row=db.execute('SELECT * FROM quiz_delivery_items WHERE task_id=? AND fingerprint=?',(task_id,_fingerprint(item))).fetchone()
        if row is None and isinstance(item.get('id'),str):
            row=db.execute('SELECT * FROM quiz_delivery_items WHERE task_id=? AND item_id=?',(task_id,item['id'])).fetchone()
        if row is None:
            # Historical event: retain only the public question shape, never keys.
            try:public=_public_item(item,f"q{data.get('position',1) if _small_int(data.get('position',1)) else 1}")
            except (KeyError,TypeError,ValueError):return {'message':'Quiz item unavailable.'}
        else:public=_public_item(json.loads(row['private_json']),row['item_id'])
        return {**numbers,'item':public} if kind=='quiz.question.emitted' else public
    if kind=='result':return _student_result(db,task_id,include_feedback=False)
    if kind=='quiz.completed':return _summary(db,task_id)
    if kind in ('error','tool.failed'):return {**numbers,'message':'Quiz generation encountered an error. Accepted questions remain available.'}
    if kind=='quiz.question.rejected':return {**numbers,'will_retry':data.get('will_retry') is True,'message':'Question did not pass validation or review.'}
    if kind=='quiz.question.failed':return {**numbers,'status':'failed','message':'Question could not be issued.'}
    if kind=='quiz.question.started':return numbers
    if kind in ('run.created','run.started','run.completed'):
        status=data.get('status')
        return {'capability':'quiz',**({'status':status} if status in ('pending','running','completed','failed') else {})}
    # Never pass model-chosen step names, tool arguments/output, corrections,
    # sources, arbitrary exception messages, or nested payloads through.
    return {**numbers,'message':'Quiz activity updated.'}


def quiz_task_view(db,task):
    """Return safe GET task shape, preserving accepted questions after failure."""
    task=dict(task);task_id=task['id']
    raw=task.get('result')
    if isinstance(raw,str):
        try:raw=json.loads(raw)
        except ValueError:raw=None
    # Supports previously stored completed results without weakening the boundary.
    if isinstance(raw,dict) and isinstance(raw.get('items'),list):
        capture_quiz_event(db,task_id,'result',raw)
    return {'id':task_id,'status':task['status'],'result':_student_result(db,task_id),
            'error':'Quiz generation encountered an error. Accepted questions remain available.' if task.get('error') else None}


def _normalize_submission(item,value):
    kind=item.get('type','single_choice')
    if kind=='single_choice':
        if type(value) is not int or not 0<=value<len(item['options']):raise QuizSubmissionError('Select one valid option index')
    elif kind=='multiple_choice':
        if not isinstance(value,list) or not value or len(value)>len(item['options']) or any(type(v) is not int or not 0<=v<len(item['options']) for v in value) or len(set(value))!=len(value):
            raise QuizSubmissionError('Select distinct valid option indices')
        value=sorted(value)
    elif kind=='short_answer':
        if not isinstance(value,str) or not value.strip() or len(value)>10000:raise QuizSubmissionError('Provide a nonempty answer of at most 10000 characters')
    elif kind=='fill_blank':
        expected={blank['id'] for blank in item['blanks']}
        if not isinstance(value,dict) or set(value)!=expected or any(not isinstance(v,str) or not v.strip() or len(v)>2000 for v in value.values()):
            raise QuizSubmissionError('Provide bounded text for each blank')
    else:raise QuizSubmissionError('Unsupported quiz item')
    return deepcopy(value)


def _score(item,identity,value):
    kind=item.get('type','single_choice')
    objective=kind in ('single_choice','multiple_choice')
    if kind=='single_choice':correct=value==item['answer_index'];key=item['answer_index']
    elif kind=='multiple_choice':correct=set(value)==set(item['answer_indices']);key=sorted(item['answer_indices'])
    elif kind=='short_answer':correct=None;key=item['answer']
    else:correct=None;key={blank['id']:blank['answer'] for blank in item['blanks']}
    return {'item_id':identity,'type':kind,'status':('correct' if correct else 'incorrect') if objective else 'manual_review',
            'submitted_answer':value,'correct_answer':key,'explanation':item['explanation'],
            'score':int(correct) if objective else None,'max_score':1 if objective else None}


def _feedback(db,task_id):
    rows=db.execute('SELECT feedback_json FROM quiz_delivery_submissions WHERE task_id=? ORDER BY rowid',(task_id,)).fetchall()
    feedback=[json.loads(row['feedback_json']) for row in rows]
    return {'feedback':feedback,'summary':{'earned':sum(f['score'] or 0 for f in feedback),
            'possible':sum(f['max_score'] or 0 for f in feedback),'manual_review':sum(f['status']=='manual_review' for f in feedback),
            'submitted':len(feedback),'unsubmitted':len(_rows(db,task_id))-len(feedback)}}


def submit_quiz(db,task_id,answers):
    """Caller holds write transaction/lock. Per-item first submissions are final.

    Batches may be partial and submitted while generation continues. Validate the
    entire batch before writing. Identical retries are idempotent; changed answers
    return 409. A later accepted question can be answered in another batch.
    """
    if not isinstance(answers,dict) or not 1<=len(answers)<=50:raise QuizSubmissionError('Submit 1–50 item answers')
    items={row['item_id']:json.loads(row['private_json']) for row in _rows(db,task_id)}
    pending=[]
    for identity,raw in answers.items():
        if identity not in items:raise QuizSubmissionError('Unknown or unissued quiz item')
        item=items[identity];value=_normalize_submission(item,raw);serialized=_json(value)
        old=db.execute('SELECT answer_json FROM quiz_delivery_submissions WHERE task_id=? AND item_id=?',(task_id,identity)).fetchone()
        if old:
            if old['answer_json']!=serialized:raise QuizSubmissionError('This item has already been submitted',409)
        else:pending.append((task_id,identity,serialized,_json(_score(item,identity,value))))
    for row in pending:db.execute('INSERT INTO quiz_delivery_submissions VALUES(?,?,?,?)',row)
    return {'task_id':task_id,**_feedback(db,task_id)}
