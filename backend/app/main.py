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

class ResumeRequest(BaseModel):
    answers: dict[str,str]

def connect():
    conn=sqlite3.connect(DB,timeout=30)
    conn.row_factory=sqlite3.Row
    return conn

def init_db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with connect() as db:
        db.executescript('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,status TEXT,request TEXT,result TEXT,error TEXT); CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,type TEXT,data TEXT,created_at REAL); CREATE INDEX IF NOT EXISTS events_task ON events(task_id,id);')
        interrupted=db.execute("SELECT id FROM tasks WHERE status IN ('running','pending')").fetchall()
        for row in interrupted:
            db.execute("UPDATE tasks SET status='failed',error=? WHERE id=?",('Process restarted; create a new task to retry.',row['id']))
            db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',(row['id'],'error',json.dumps({'message':'Worker interrupted by process restart. No automatic replay of external calls.'}),time.time()))

@app.on_event('startup')
def startup(): init_db()

def get_task(task_id):
    with connect() as db: row=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
    if row is None: raise HTTPException(404,'Unknown task')
    return dict(row)

def event(task_id,kind,data):
    with LOCK,connect() as db: db.execute('INSERT INTO events(task_id,type,data,created_at) VALUES(?,?,?,?)',(task_id,kind,json.dumps(data,ensure_ascii=False),time.time()))

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
        if request['provider']=='fake': result=fake_run(capability,inputs,emit)
        else:
            from .agno_adapter import run_agno
            result=run_agno(capability,inputs,emit)
            if capability!='exam': result=verify_grounding(result,inputs.get('sources',[])+result.get('retrieved_sources',[]))
            if capability=='quiz' and result.get('quiz_status', {}).get('status') != 'failed': validate_quiz(result)
            if capability=='exam':
                from .exam_blueprint import validate_generated_exam
                validate_generated_exam(inputs['blueprint'],result.get('exam',result))
        if capability=='quiz':
            if result.get('quiz_status', {}).get('status') == 'failed':
                reason = 'No quiz questions passed generation and review.'
                emit('result',result); status(task_id,'failed',result,reason)
                emit('error',{'message':reason}); emit('run.completed',{'status':'failed'})
                return
            if request['provider']=='fake':
                for item in result['items']:
                    emit('quiz.question',item)
        if capability=='exam':
            from .exam_blueprint import render_exam
            canonical={key:result[key] for key in ('version','title','duration_minutes','total_points','output_format','instructions','style_descriptors','sections','seed','answer_key')}
            result['export']=render_exam(canonical)
        if capability=='visualize':
            from .visualize import finalize_visual
            result['visualization']=finalize_visual(result)
        emit('progress',{'percent':100,'message':'Result ready'})
        emit('result',result); status(task_id,'completed',result); emit('run.completed',{'status':'completed'})
    except Exception as exc:
        # Never include request secrets or full tracebacks in user-facing events.
        message=str(exc)[:1000]
        for key in ('OPENAI_API_KEY','TAVILY_API_KEY'):
            secret=os.getenv(key)
            if secret: message=message.replace(secret,'[redacted]')
        status(task_id,'failed',error=message); emit('tool.failed',{'message':message}); emit('error',{'message':message}); emit('run.completed',{'status':'failed'})

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
    return {'id':task_id,'status':task['status'],'result':json.loads(task['result']) if task['result'] else None,'error':task['error']}

@app.post('/api/tasks/{task_id}/resume',status_code=202)
def resume_task(task_id:str,body:ResumeRequest):
    if sum(map(len,body.answers.values()))>10000: raise HTTPException(422,'Answers too long')
    with LOCK,connect() as db:
        task=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not task: raise HTTPException(404,'Unknown task')
        if task['status']!='paused': raise HTTPException(409,'Task is not awaiting an answer')
        request=json.loads(task['request'])
        card=db.execute("SELECT data FROM events WHERE task_id=? AND type='question' ORDER BY id DESC LIMIT 1",(task_id,)).fetchone()
        if not card: raise HTTPException(409,'Task question state unavailable')
        try: request['inputs'].update(confirmed_inputs(request['capability'],json.loads(card['data']),body.answers))
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        db.execute("UPDATE tasks SET request=?,status='pending' WHERE id=?",(json.dumps(request),task_id))
    event(task_id,'run.resumed',{'answers':body.answers}); launch(task_id)
    return {'id':task_id,'status':'pending'}

@app.get('/api/tasks/{task_id}/events')
async def events(task_id:str,request:Request,after:int=0):
    get_task(task_id)
    try: cursor=max(after,int(request.headers.get('last-event-id','0')))
    except ValueError: raise HTTPException(422,'Invalid event cursor')
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            with connect() as db: rows=db.execute('SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id',(task_id,cursor)).fetchall()
            for row in rows:
                value=dict(row); value['data']=json.loads(value['data']); cursor=value['id']
                yield f'id: {cursor}\nevent: {value["type"]}\ndata: {json.dumps(value,ensure_ascii=False)}\n\n'
            if get_task(task_id)['status'] in ('completed','failed') and not rows: break
            yield ': heartbeat\n\n'; await asyncio.sleep(.25)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

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
    if asset not in ('app.js','style.css'): raise HTTPException(404)
    return FileResponse(ROOT/'frontend'/asset)
