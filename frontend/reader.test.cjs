// Module UI behavior driven by real task/SSE output and hostile reference fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
class Node {
  constructor(tag='') { this.tag=tag; this.tagName=tag.toUpperCase(); this.children=[]; this.handlers={}; this.attrs={}; this.textContent=''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute(k,v) { this.attrs[k]=String(v); }
  addEventListener(k,fn) { this.handlers[k]=fn; }
  scrollIntoView() { this.scrolled=true; }
  focus() { this.focused=true; }
  pause() { this.paused=true; }
  set innerHTML(_) { throw new Error('HTML insertion prohibited'); }
}
const nodes = n => [n,...n.children.flatMap(nodes)];
const byRole = (n, role) => nodes(n).filter(x=>x.attrs['data-reader-role']===role);
const sources=[{id:'p1',title:'<img src=x>',page:7,text:'First. Exact <script>quote</script>. Last.'},
 {id:'c1',title:'Timed caption',start_seconds:65.5,end_seconds:68,text:'The timed words.'}];
const taskResult = JSON.parse(execFileSync('python',['-c',`import json,sys,tempfile,time\nfrom pathlib import Path\nfrom fastapi.testclient import TestClient\nfrom app import main\nwith tempfile.TemporaryDirectory() as temp:\n main.DB=Path(temp)/'reader.sqlite3'\n with TestClient(main.app) as client:\n  task=client.post('/api/tasks',json={'capability':'immersive_reading','provider':'fake','inputs':{'prompt':'Read these','sources':json.loads(sys.stdin.read())}}).json()\n  for _ in range(100):\n   result=client.get('/api/tasks/'+task['id']).json()\n   if result['status'] in ('completed','failed'): break\n   time.sleep(.01)\n  assert result['status']=='completed',result\n  stream=client.get('/api/tasks/'+task['id']+'/events').text\n  print(json.dumps({'id':task['id'],'events':[json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: ')]}))`],{cwd:__dirname+'/../backend',input:JSON.stringify(sources),encoding:'utf8',stdio:['pipe','pipe','pipe']}));
const context={document:{createElement:tag=>new Node(tag)},console};
vm.runInNewContext(fs.readFileSync(__dirname+'/reader.js','utf8'),context);
assert.ok(context.TutorReader?.create,'reader module is available');
const container=new Node('section'), reader=context.TutorReader.create({container});
reader.beginTask({taskId:taskResult.id,sources});
for (const event of taskResult.events) reader.handleEvent(event);
assert.equal(byRole(container,'citation-link').length,2,'result citations should be navigable');
const click=node=>node.handlers.click({preventDefault(){}});
click(byRole(container,'citation-link')[0]);
assert.equal(nodes(container).filter(n=>n.tag==='mark')[0].textContent,sources[0].text);
assert.ok(byRole(container,'excerpt')[0].focused);
assert.match(byRole(container,'location')[0].textContent,/Page 7/);
click(byRole(container,'citation-link')[1]);
assert.match(byRole(container,'location')[0].textContent,/01:05.5/);
assert.equal(nodes(container).filter(n=>n.tag==='mark')[0].textContent,sources[1].text);
assert.equal(nodes(container).filter(n=>n.tag==='video'||n.tag==='iframe'||n.tag==='script').length,0);
const event=(id,data,type='reader.located')=>({id,task_id:taskResult.id,type,data});
reader.handleEvent(event(100,{source_id:'p1',quote:'Exact <script>quote</script>',page:7}));
const literalLink=byRole(container,'citation-link').at(-1);click(literalLink);
assert.equal(nodes(container).filter(n=>n.tag==='mark')[0].textContent,'Exact <script>quote</script>');
const unchanged=byRole(container,'location')[0].textContent;
for (const invalid of [
 {source_id:'unknown',quote:'Exact'}, {source_id:'p1',quote:'exact'},
 {source_id:'p1',quote:'Exact',page:99}, {source_id:'p1',quote:''},
 {source_id:'c1',quote:'timed',start_seconds:66},
 {source_id:'c1',quote:'timed',start_seconds:Infinity}
]) {
 const before=byRole(container,'citation-link').length;
 reader.handleEvent(event(101,invalid));assert.equal(byRole(container,'citation-link').length,before);
 assert.equal(byRole(container,'location')[0].textContent,unchanged);
}
reader.handleEvent(event(102,{source_id:'p1',quote:'Exact <script>quote</script>',page:7}));
assert.equal(byRole(container,'citation-link').length,3,'replayed citation deduplicated');
reader.handleEvent({task_id:'other-task',type:'reader.located',data:{source_id:'p1',quote:'First'}});
assert.equal(byRole(container,'citation-link').length,3,'other task events ignored');
reader.beginTask({taskId:'new',sources:[{id:'p1',text:'new text',page:2}]});
click(literalLink);assert.equal(nodes(container).filter(n=>n.tag==='mark').length,0,'stale click cannot navigate new task');
reader.handleEvent({task_id:'new',type:'result',data:{citations:[{source_id:'p1',quote:'new text'}]}});
click(byRole(container,'citation-link')[0]);assert.match(byRole(container,'location')[0].textContent,/Page 2/);
reader.beginTask({taskId:'duplicate',sources:[{id:'x',text:'one'},{id:'x',text:'two'}]});
reader.handleEvent({task_id:'duplicate',type:'reader.located',data:{source_id:'x',quote:'one'}});
assert.equal(byRole(container,'citation-link').length,0,'ambiguous source IDs fail closed');
// Optional playback is restricted to local lesson artifacts; timestamp seek waits for metadata.
const local='/api/media/'+'a'.repeat(32)+'/lesson.mp4';
reader.beginTask({taskId:'media',sources:[{id:'clip',text:'caption',start_seconds:5,end_seconds:8,media_url:local}]});
reader.handleEvent({task_id:'media',type:'reader.located',data:{source_id:'clip',quote:'caption',start_seconds:5}});
click(byRole(container,'citation-link')[0]);
const player=byRole(container,'player')[0];assert.equal(player.src,local);assert.equal(player.currentTime,undefined);
player.duration=10;player.handlers.loadedmetadata();assert.equal(player.currentTime,5);
player.currentTime=0;player.duration=4;player.handlers.loadedmetadata();assert.equal(player.currentTime,0);
assert.match(byRole(container,'message')[0].textContent,/outside/);
reader.beginTask({taskId:'changed',sources:[{id:'x',text:'new'}]});
player.duration=10;player.handlers.loadedmetadata();assert.equal(player.currentTime,0,'stale metadata cannot seek');
assert.equal(player.paused,true,'old media pauses on task change');
for (const unsafe of ['https://example.org/lesson.mp4','//example.org/lesson.mp4',local+'?redirect=evil','/api/media/../lesson.mp4','javascript:bad()',local.replace('lesson.mp4','other.mp4')]) {
 reader.beginTask({taskId:'unsafe',sources:[{id:'clip',text:'caption',start_seconds:5,media_url:unsafe}]});
 reader.handleEvent({task_id:'unsafe',type:'reader.located',data:{source_id:'clip',quote:'caption'}});
 click(byRole(container,'citation-link')[0]);assert.equal(byRole(container,'player').length,0);
}
reader.reset();assert.equal(container.hidden,true);
console.log('PASS reader: real task/SSE, page/caption links, literal highlighting, unsafe/unknown/mismatched refs, dedup and stale task isolation');
