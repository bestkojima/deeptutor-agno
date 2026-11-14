// UI behavior through task SSE and the real public plot endpoint; no model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
function plot(spec) {
  return JSON.parse(execFileSync('python', ['-c', `import json,sys\nfrom fastapi.testclient import TestClient\nfrom app.main import app\nr=TestClient(app).post('/api/visualize/plot',json=json.loads(sys.stdin.read()))\nprint(json.dumps({'ok':r.status_code==200,'payload':r.json()}))`],
    {cwd: __dirname + '/../backend', input: JSON.stringify(spec), encoding: 'utf8', env: {...process.env, TUTOR_DB: ':memory:'}, stdio: ['pipe', 'pipe', 'pipe']}));
}
function createTask(body) {
  return JSON.parse(execFileSync('python', ['-c', `import json,sys,tempfile,time
from pathlib import Path
from fastapi.testclient import TestClient
from app import main
with tempfile.TemporaryDirectory() as temp:
 main.DB=Path(temp)/'test.sqlite3'
 with TestClient(main.app) as client:
  response=client.post('/api/tasks',json=json.loads(sys.stdin.read()))
  assert response.status_code==202,response.text
  task=response.json()
  for _ in range(100):
   snapshot=client.get('/api/tasks/'+task['id']).json()
   if snapshot['status'] in ('completed','failed'): break
   time.sleep(.01)
  assert snapshot['status']=='completed',snapshot
  events=client.get('/api/tasks/'+task['id']+'/events').text
  print(json.dumps({'task':task,'events':[json.loads(line[6:]) for line in events.splitlines() if line.startswith('data: ')]}))`],
    {cwd: __dirname + '/../backend', input: JSON.stringify(body), encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe']}));
}
let taskEvents = [];
class Element {
  constructor(tag='') { this.tag=tag; this.children=[]; this.handlers={}; this.attributes={}; this.hidden=false; this.value=''; this.style={}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; }
  addEventListener(type, fn) { this.handlers[type]=fn; }
  setAttribute(key,value) { this.attributes[key]=String(value); }
  set innerHTML(value) { throw new Error('Untrusted HTML must not be injected'); }
}
const elements = new Map();
const get = id => {
  const find = node => node.id===id ? node : node.children.map(find).find(Boolean);
  for (const node of elements.values()) { const match=find(node); if(match) return match; }
  if(!elements.has(id)) elements.set(id,new Element());
  return elements.get(id);
};
class Stream {
  static CLOSED=2;
  constructor() { this.listeners={}; Stream.last=this; }
  addEventListener(type,fn) { this.listeners[type]=fn; }
  emit(id,type,data) { this.listeners[type]?.({data:JSON.stringify({id,type,data})}); }
  close() {}
}
const requests=[]; const pending=[]; let defer=false;
const context={document:{getElementById:get,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)},EventSource:Stream,console,
 fetch:async(path,options)=>{
  requests.push({path,body:options&&JSON.parse(options.body)});
  if(path==='/api/tasks') {
    const result=createTask(JSON.parse(options.body));taskEvents=result.events;return {ok:true,json:async()=>result.task};
  }
  if(path==='/api/visualize/plot') {
    if(defer) return new Promise(resolve=>pending.push(resolve));
    const result=plot(JSON.parse(options.body));return {ok:result.ok,json:async()=>result.payload};
  }
  return {ok:true,json:async()=>path==='/api/capabilities'?{capabilities:[{id:'visualize'}]}:{id:'task-1'}};
 }};
vm.runInNewContext(fs.readFileSync(__dirname+'/app.js','utf8'),context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const spec=a=>({domain:[-2,2],samples:5,curves:[{function:'quadratic',parameters:{a,b:0,c:0},label:'Quadratic'}]});
const descendants=node=>[node,...node.children.flatMap(descendants)];
const polyline=()=>descendants(get('visualization-plot')).find(node=>node.tag==='polyline');
(async()=>{
 await tick();
 assert.equal(typeof get('plot-example').handlers.click, 'function', 'graph should be usable without a model task');
 await get('plot-example').handlers.click();
 assert.ok(polyline());
 assert.equal(requests.filter(r=>r.path==='/api/tasks').length,0);
 get('inputs').value='{"prompt":"Plot a quadratic"}';get('capability').value='visualize';get('provider').value='fake';
 await get('task-form').handlers.submit({preventDefault(){}});
 taskEvents.forEach(event=>Stream.last.emit(event.id,event.type,event.data));
 assert.equal(get('status').textContent,'Completed');
 for(const [i,a] of [1,-1,0].entries()) {
   const response=plot(spec(a)); assert.equal(response.ok,true);
   assert.deepEqual(response.payload.computed.curves[0].points.map(p=>p[1]),[4*a,a,0,a,4*a]);
   Stream.last.emit(i+1000,'result',{visualization:response.payload});
   assert.equal(get('visualization').hidden,false);
   assert.ok(polyline(),'task result should show a safe numeric graph');
   assert.equal(get('coefficient-a').value,String(a));
 }
 get('coefficient-a').value='2';await get('coefficient-a').handlers.input();await tick();
 assert.equal(requests.at(-1).path,'/api/visualize/plot');assert.equal(requests.at(-1).body.curves[0].parameters.a,2);
 assert.match(get('plot-status').textContent,/Updated/);
 assert.equal(requests.filter(r=>r.path==='/api/tasks').length,1,'drag must not re-run model/task');
 assert.match(get('plot-equation').textContent,/2/);
 assert.equal(plot({curves:[{function:'quadratic',parameters:{a:1000001}}]}).ok,false,'public API rejects out-of-bounds input');
 const oldPolyline=polyline();
 get('coefficient-a').value='NaN';await get('coefficient-a').handlers.input();
 assert.match(get('plot-status').textContent,/finite|valid/i);assert.equal(polyline(),oldPolyline);
 defer=true;
 get('coefficient-a').value='3';get('coefficient-a').handlers.input();
 get('coefficient-a').value='4';get('coefficient-a').handlers.input();
 pending[1]({ok:true,json:async()=>plot(spec(4)).payload});await tick();const newest=polyline();
 pending[0]({ok:true,json:async()=>plot(spec(3)).payload});await tick();assert.equal(polyline(),newest);assert.match(get('plot-equation').textContent,/4/);
 get('coefficient-a').value='5';get('coefficient-a').handlers.input();pending[2]({ok:false,json:async()=>({detail:'Rejected plot'})});await tick();
 assert.match(get('plot-status').textContent,/Rejected plot/);assert.equal(polyline(),newest);
 get('coefficient-a').value='6';get('coefficient-a').handlers.input();
 Stream.last.emit(1010,'result',{visualization:{type:'html',content:'<script>bad()</script>',rendered:false}});
 pending[3]({ok:true,json:async()=>plot(spec(6)).payload});await tick();assert.equal(get('visualization').hidden,true);
 Stream.last.emit(1011,'result',{visualization:{...plot(spec(1)).payload,computed:{curves:[{points:[[0,'<script>']]}],y_range:[0,1]}}});
 assert.equal(polyline(),undefined);assert.match(get('plot-status').textContent,/Invalid/);
 assert.ok(descendants(get('visualization-plot')).every(n=>!['script','iframe','foreignObject'].includes(n.tag)));
 console.log('PASS: three known graphs, public plot boundary, drag without task rerun, validation, failure, safe SVG and stale response isolation');
})().catch(error=>{console.error(error);process.exitCode=1;});
