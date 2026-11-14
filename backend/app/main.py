"""Single-user localhost API. SQLite journal provides durable, replayable SSE."""
import asyncio
import importlib.util
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from .preview import prepare_preview, confirmed_inputs
from .quiz_delivery import (QuizSubmissionError, capture_quiz_event, init_quiz_db,
                            public_quiz_event, quiz_task_view, submit_quiz)
from .core import CAPABILITIES, fake_run, verify_grounding, validate_quiz, validate_sources

ROOT=Path(__file__).resolve().parents[2]
DB=Path(os.getenv('TUTOR_DB',str(ROOT/'runs.sqlite3')))
LOCK=threading.RLock()
app=FastAPI(title='Agno Tutor Workbench',version='0.1.0')

class TaskRequest(BaseModel):
    capability: str
    inputs: dict=Field(default_factory=dict)
    provider: Literal['fake','agno']='fake'
class BlueprintRequest(BaseModel):
    sample_text: str = Field(min_length=20,max_length=60000)

class QuizSubmission(BaseModel):
    answers: dict[str,object]

class ResumeRequest(BaseModel):
    answers: dict[str,str]

def connect():
    conn=sqlite3.connect(DB,timeout=30)
    conn.row_factory=sqlite3.Row
    return conn

def confirmed_research(task_request):
    return (task_request.get('provider') == 'agno' and task_request.get('capability') == 'research'
            and bool(task_request.get('inputs', {}).get('confirmed_outline')))


def init_db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with connect() as db:
        db.executescript('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,status TEXT,request TEXT,result TEXT,error TEXT); CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,type TEXT,data TEXT,created_at REAL); CREATE INDEX IF NOT EXISTS events_task ON events(task_id,id);')
        init_quiz_db(db)
        db.execute('BEGIN IMMEDIATE')
        interrupted=db.execute("SELECT id,request,result FROM tasks WHERE status IN ('running','pending')").fetchall()
        for row in interrupted:
            if confirmed_research(json.loads(row['request'])):
                db.execute("UPDATE tasks SET status='interrupted',error=NULL WHERE id=?",(row['id'],))
                db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',
                           (row['id'],'research.interrupted',json.dumps({'message':'Research interrupted; resume explicitly to reuse completed evidence.'}),time.time()))
                continue
            prior=json.loads(row['result']) if row['result'] else {}
            if prior.get('renderer')=='trusted-quadratic-animation':
                retained={**prior,'fallback_used':True,'revision_status':'interrupted'}
                db.execute("UPDATE tasks SET status='completed',result=?,error=NULL WHERE id=?",
                           (json.dumps(retained,ensure_ascii=False),row['id']))
                db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',
                           (row['id'],'result',json.dumps(retained,ensure_ascii=False),time.time()))
                db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',
                           (row['id'],'run.completed',json.dumps({'status':'completed','revision_status':'interrupted','retained_previous':True}),time.time()))
                continue
            db.execute("UPDATE tasks SET status='failed',error=? WHERE id=?",('Process restarted; create a new task to retry.',row['id']))
            db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',(row['id'],'error',json.dumps({'message':'Worker interrupted by process restart. No automatic replay of external calls.'}),time.time()))
            db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',
                       (row['id'],'run.completed',json.dumps({'status':'failed'}),time.time()))

@app.on_event('startup')
def startup(): init_db()

def get_task(task_id):
    with connect() as db: row=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
    if row is None: raise HTTPException(404,'Unknown task')
    return dict(row)

def insert_event(db,task_id,kind,data):
    row=db.execute('SELECT request FROM tasks WHERE id=?',(task_id,)).fetchone()
    if row and json.loads(row['request']).get('capability')=='quiz':
        data=capture_quiz_event(db,task_id,kind,data)
    db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',
               (task_id,kind,json.dumps(data,ensure_ascii=False),time.time()))


def event(task_id,kind,data):
    with LOCK,connect() as db:
        insert_event(db,task_id,kind,data)


def finish_task(task_id,value,result=None,error=None,completion=None):
    """Make the terminal state and its SSE frames visible in the same transaction."""
    with LOCK,connect() as db:
        if result is not None:
            insert_event(db,task_id,'result',result)
        if error:
            insert_event(db,task_id,'error',{'message':error})
        insert_event(db,task_id,'run.completed',{'status':value,**(completion or {})})
        db.execute('UPDATE tasks SET status=?,result=?,error=? WHERE id=?',
                   (value,json.dumps(result,ensure_ascii=False) if result is not None else None,error,task_id))


def status(task_id,value,result=None,error=None):
    with LOCK,connect() as db: db.execute('UPDATE tasks SET status=?,result=?,error=? WHERE id=?',(value,json.dumps(result,ensure_ascii=False) if result is not None else None,error,task_id))

def execute(task_id):
    task=get_task(task_id); request=json.loads(task['request']); inputs=request['inputs']; capability=request['capability']
    emit=lambda kind,data:event(task_id,kind,data)
    try:
        status(task_id,'running'); emit('run.started',{'capability':capability,'provider':request['provider']})
        if capability in ('ask_questions','research') and 'answers' not in inputs:
            question=prepare_preview(capability, inputs, request['provider'], emit)
            with LOCK,connect() as db:
                db.execute("UPDATE tasks SET status='paused' WHERE id=?",(task_id,))
                db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',
                           (task_id,'question',json.dumps(question,ensure_ascii=False),time.time()))
            return
        emit('progress',{'percent':10,'message':'Validating inputs and preparing workflow'})
        validate_sources(inputs.get('sources',[]))
        if capability=='video_lesson' and request['provider']=='fake' and 'animation' in inputs:
            from .media import build_lesson
            emit('step.started',{'name':'render_trusted_animation'})
            result=build_lesson({'animation':inputs['animation'],'tts':inputs.get('tts','none')})
            emit('step.completed',{'name':'render_trusted_animation'})
        elif request['provider']=='fake': result=fake_run(capability,inputs,emit)
        else:
            from .agno_adapter import run_agno
            if confirmed_research(request):
                from .research_checkpoint import ResearchCheckpointStore
                result=run_agno(capability,inputs,emit,research_checkpoint=ResearchCheckpointStore(DB,task_id,inputs))
            else:
                result=run_agno(capability,inputs,emit)
            if capability!='exam': result=verify_grounding(result,inputs.get('sources',[])+result.get('retrieved_sources',[]))
            if capability=='quiz' and result.get('quiz_status', {}).get('status') != 'failed': validate_quiz(result)
            if capability=='exam':
                from .exam_blueprint import validate_generated_exam
                validate_generated_exam(inputs['blueprint'],result.get('exam',result))
        if capability=='quiz':
            if result.get('quiz_status', {}).get('status') == 'failed':
                reason = 'No quiz questions passed generation and review.'
                finish_task(task_id,'failed',result,reason)
                return
            if request['provider']=='fake':
                for item in result['items']:
                    emit('quiz.question',item)
        if capability=='exam':
            from .exam_blueprint import render_exam
            canonical={key:result[key] for key in ('version','title','duration_minutes','total_points','output_format','instructions','style_descriptors','sections','seed','answer_key')}
            if 'artifacts' in inputs:
                from .exam_artifacts import build_exam_artifacts
                canonical, artifact_manifest = build_exam_artifacts(canonical, inputs['blueprint'], inputs['artifacts'], request['provider'])
                result.update(canonical)
                result['artifacts'] = artifact_manifest
            result['export']=render_exam(canonical)
        if capability=='visualize':
            from .visualize import finalize_visual
            result['visualization']=finalize_visual(result)
        emit('progress',{'percent':100,'message':'Result ready'})
        finish_task(task_id,'completed',result)
    except Exception as exc:
        # Never include request secrets or full tracebacks in user-facing events.
        message=str(exc)[:1000]
        for key in ('OPENAI_API_KEY','TAVILY_API_KEY'):
            secret=os.getenv(key)
            if secret: message=message.replace(secret,'[redacted]')
        emit('tool.failed',{'message':message})
        finish_task(task_id,'failed',error=message)

def launch(task_id): threading.Thread(target=execute,args=(task_id,),daemon=True).start()

@app.get('/api/capabilities')
def capabilities():
    installed=importlib.util.find_spec('agno') is not None
    return {'capabilities':[{'id':c,'label':c.replace('_',' ').title(),'available':True} for c in CAPABILITIES], 'providers':{'fake':{'available':True,'reason':'Deterministic fixtures, not model-generated content'},'agno':{'available':installed and bool(os.getenv('OPENAI_API_KEY')),'reason':'Requires Agno and server-side OPENAI_API_KEY; no API key requested by this app'}},'limits':{'ingestion':'Supply excerpts or import VTT/SRT; raw PDF/audio/video extraction is not implemented','manim':'Disabled until isolated renderer is configured','memory':'Reserved hooks only; no personalization','security':'Local single-user only. Bind 127.0.0.1; no multi-user authentication.'}}

@app.post('/api/visualize/plot')
def compute_plot(spec: dict):
    from .visualize import render_function_graph
    try:
        return render_function_graph(spec)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/sources/captions')
async def ingest_captions(request: Request, filename: str):
    from .source_ingestion import IngestionError, MAX_BYTES, ingest_source
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, 'Caption upload exceeds 2 MB')
        data.extend(chunk)
    try:
        return {'sources': ingest_source(bytes(data), filename=filename), 'transcribed': False}
    except IngestionError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/api/exam/blueprint')
def exam_blueprint(body:BlueprintRequest):
    if not os.getenv('OPENAI_API_KEY') or importlib.util.find_spec('agno') is None:
        raise HTTPException(503,'Configure Agno and server-side credentials to extract sample text')
    from .preview import extract_exam_blueprint
    try:
        blueprint=extract_exam_blueprint(body.sample_text)
    except ValueError as exc:
        raise HTTPException(422,'Sample could not be converted to a complete blueprint; check missing or ambiguous details.') from exc
    except Exception as exc:
        raise HTTPException(502,'Model provider could not extract the blueprint.') from exc
    return {'blueprint':blueprint,'review_required':True}

@app.post('/api/tasks',status_code=202)
def create_task(body:TaskRequest):
    if body.capability not in CAPABILITIES: raise HTTPException(422,'Unknown capability')
    if len(json.dumps(body.inputs))>2_000_000: raise HTTPException(413,'Inputs exceed 2 MB limit')
    if {'answers','clarification','confirmed_outline','outline_revision'} & body.inputs.keys():
        raise HTTPException(422,'Confirmation fields can only be supplied through the resume endpoint')
    if body.provider=='agno' and (not os.getenv('OPENAI_API_KEY') or importlib.util.find_spec('agno') is None):
        raise HTTPException(503,'Agno and server-side model credentials must be configured')
    if not isinstance(body.inputs.get('tools',[]),list) or any(not isinstance(x,str) for x in body.inputs.get('tools',[])):
        raise HTTPException(422,'Tools must be a list of names')
    if set(body.inputs.get('tools',[]))-{'calculator','source_search','local_search'}: raise HTTPException(422,'Unknown or disabled tool. Allowed: calculator, source_search')
    task_id=uuid.uuid4().hex
    with connect() as db: db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)',(task_id,'pending',body.model_dump_json(),None,None))
    event(task_id,'run.created',{'status':'pending'}); launch(task_id)
    return {'id':task_id,'status':'pending'}

@app.get('/api/tasks/{task_id}')
def read_task(task_id:str):
    task=get_task(task_id)
    if json.loads(task['request']).get('capability')=='quiz':
        with LOCK,connect() as db:
            return quiz_task_view(db,task)
    out={'id':task_id,'status':task['status'],'result':json.loads(task['result']) if task['result'] else None,'error':task['error']}
    if confirmed_research(json.loads(task['request'])) and task['status'] in ('interrupted','failed'):
        out['can_resume_research']=True
        with connect() as db:
            out['last_event_id']=db.execute('SELECT COALESCE(MAX(id),0) AS last_id FROM events WHERE task_id=?',(task_id,)).fetchone()['last_id']
    if task['status']=='paused':
        with connect() as db:
            card=db.execute("SELECT data FROM events WHERE task_id=? AND type='question' ORDER BY id DESC LIMIT 1",(task_id,)).fetchone()
        if card: out['question']=json.loads(card['data'])
    return out

@app.post('/api/tasks/{task_id}/quiz/submit')
def submit_quiz_answers(task_id:str, body:QuizSubmission):
    task=get_task(task_id)
    if json.loads(task['request']).get('capability')!='quiz':
        raise HTTPException(409,'Task is not a quiz')
    try:
        with LOCK,connect() as db:
            return submit_quiz(db,task_id,body.answers)
    except QuizSubmissionError as exc:
        raise HTTPException(exc.status_code,str(exc)) from exc


@app.post('/api/tasks/{task_id}/resume',status_code=202)
def resume_task(task_id:str,body:ResumeRequest):
    if sum(map(len,body.answers.values()))>10000: raise HTTPException(422,'Answers too long')
    with LOCK,connect() as db:
        db.execute("BEGIN IMMEDIATE")
        task=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not task: raise HTTPException(404,'Unknown task')
        request=json.loads(task['request'])
        if task['status'] in ('interrupted','failed') and confirmed_research(request):
            if body.answers:
                raise HTTPException(409,'Only confirmed interrupted research can resume without new answers')
        elif task['status']=='paused':
            card=db.execute("SELECT data FROM events WHERE task_id=? AND type='question' ORDER BY id DESC LIMIT 1",(task_id,)).fetchone()
            if not card: raise HTTPException(409,'Task question state unavailable')
            try: request['inputs'].update(confirmed_inputs(request['capability'],json.loads(card['data']),body.answers))
            except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        else:
            raise HTTPException(409,'Task is not awaiting an answer or interrupted research resume')
        db.execute("UPDATE tasks SET request=?,status='pending',error=NULL WHERE id=?",(json.dumps(request),task_id))
    event(task_id,'run.resumed',{'answers':body.answers}); launch(task_id)
    return {'id':task_id,'status':'pending'}

@app.get('/api/tasks/{task_id}/events')
async def events(task_id:str,request:Request,after:int=0):
    is_quiz=json.loads(get_task(task_id)['request']).get('capability')=='quiz'
    try: cursor=max(after,int(request.headers.get('last-event-id','0')))
    except ValueError: raise HTTPException(422,'Invalid event cursor')
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            with connect() as db:
                db.execute('BEGIN')
                rows=db.execute('SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id LIMIT 128',
                                (task_id,cursor)).fetchall()
                task_status=db.execute('SELECT status FROM tasks WHERE id=?',(task_id,)).fetchone()['status']
                values=[]
                for row in rows:
                    value=dict(row)
                    value['data']=json.loads(value['data'])
                    if is_quiz:
                        value['data']=public_quiz_event(db,task_id,value['type'],value['data'])
                    values.append(value)
            for value in values:
                cursor=value['id']
                yield f'id: {cursor}\nevent: {value["type"]}\ndata: {json.dumps(value,ensure_ascii=False)}\n\n'
            if len(values)==128: continue
            if task_status in ('completed','failed','interrupted'): break
            yield ': heartbeat\n\n'; await asyncio.sleep(.25)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.get('/api/exam-artifacts/{artifact_id}/{filename:path}')
def exam_artifact_file(artifact_id:str, filename:str):
    from .exam_artifacts import resolve_artifact, FORMATS
    try: path=resolve_artifact(artifact_id,filename)
    except (ValueError,FileNotFoundError): raise HTTPException(404,'Unknown exam artifact')
    return FileResponse(path,media_type=FORMATS[filename],filename=filename,
                        headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"})

class AnimationRevision(BaseModel):
    animation: dict


def render_video_revision(task_id, previous, animation):
    from .media import build_lesson
    status(task_id,'running',previous)
    event(task_id,'step.started',{'name':'render_trusted_animation_revision'})
    try:
        updated=build_lesson({'animation':animation,'tts':'none'})
    except Exception:
        retained={**previous,'fallback_used':True,'revision_status':'failed'}
        event(task_id,'step.failed',{'name':'render_trusted_animation_revision','retained_previous':True})
        finish_task(task_id,'completed',retained,completion={'revision_status':'failed','retained_previous':True})
        return
    updated['revision_status']='completed'
    event(task_id,'step.completed',{'name':'render_trusted_animation_revision'})
    finish_task(task_id,'completed',updated,completion={'revision_status':'completed'})


@app.post('/api/tasks/{task_id}/video/revise',status_code=202)
def revise_video(task_id:str, body:AnimationRevision):
    from .math_lesson_media import validate_animation
    try: spec=validate_animation(body.animation)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    with LOCK,connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute('SELECT request,status,result FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not row: raise HTTPException(404,'Unknown task')
        previous=json.loads(row['result']) if row['result'] else {}
        if (row['status']!='completed' or json.loads(row['request'])['capability']!='video_lesson'
                or previous.get('renderer')!='trusted-quadratic-animation'):
            raise HTTPException(409,'Task needs a completed trusted animation before revision')
        db.execute("UPDATE tasks SET status='pending',error=NULL WHERE id=?",(task_id,))
    event(task_id,'video.revision.started',{'uses_fixed_template':True})
    threading.Thread(target=render_video_revision,args=(task_id,previous,spec),daemon=True).start()
    return {'id':task_id,'status':'pending'}


@app.get('/api/media/{media_id}/{filename}')
def media_file(media_id:str,filename:str):
    from .media import resolve_media
    try: path=resolve_media(media_id,filename)
    except (ValueError,FileNotFoundError): raise HTTPException(404,'Unknown media')
    return FileResponse(path,headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; media-src 'self'; style-src 'unsafe-inline'"})

@app.get('/')
def index(): return FileResponse(ROOT/'frontend'/'index.html')
@app.get('/{asset}')
def assets(asset:str):
    if asset not in ('app.js','style.css','reader.js','reader.css','quiz.js'): raise HTTPException(404)
    return FileResponse(ROOT/'frontend'/asset)
