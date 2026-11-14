// No dependencies: exercise UI event behavior in a minimal DOM, not a browser layout test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag = '') { this.tag = tag; this.children = []; this.handlers = {}; this.hidden = false; this.disabled = false; this.value = ''; this.textContent = ''; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(type, handler) { this.handlers[type] = handler; }
}
const elements = new Map();
const get = id => elements.get(id) || (elements.set(id, new Element()), elements.get(id));
const requests = [];
class Stream {
  static CLOSED = 2;
  constructor(url) { this.url = url; this.listeners = {}; Stream.last = this; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  emit(id, type, data) { this.listeners[type]?.({data: JSON.stringify({id, type, data}), lastEventId: String(id)}); }
  close() { this.closed = true; }
}
const context = {document: {getElementById: id => {
  for (const element of get('question-fields').children) if (element.id === id) return element;
  return get(id);
}, createElement: tag => new Element(tag)}, EventSource: Stream,
  fetch: async (path, options) => { requests.push({path, options}); return {ok: true, json: async () => path === '/api/capabilities' ? {capabilities: [{id: 'chat', label: 'Chat'}]} : {id: 'task-1'}}; }, console};
vm.runInNewContext(fs.readFileSync(__dirname + '/app.js', 'utf8'), context);
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  await tick();
  assert.equal(get('start').disabled, false);
  get('inputs').value = '[]';
  await get('task-form').handlers.submit({preventDefault() {}});
  assert.match(get('request-error').textContent, /JSON object/);
  get('inputs').value = '{"prompt":"Hello"}'; get('capability').value = 'chat'; get('provider').value = 'fake';
  await get('task-form').handlers.submit({preventDefault() {}});
  const stream = Stream.last;
  stream.emit(1, 'tool.started', {tool: '<img src=x onerror=alert(1)>'});
  stream.emit(1, 'tool.started', {tool: 'duplicate'});
  assert.equal(get('trace').children.length, 1);
  assert.match(get('trace').children[0].children[0].children[0].textContent, /<img/);
  stream.onerror({}); assert.equal(get('connection').textContent, 'Reconnecting…');
  stream.emit(2, 'progress', {percent: 50, message: 'Halfway'}); assert.equal(get('progress').value, 50);
  stream.emit(3, 'question', {questions: [{id: 'topic', question: 'Which topic?'}]});
  assert.equal(get('questions').hidden, false);
  get('question-fields').children[1].value = 'Algebra';
  await get('answers-form').handlers.submit({preventDefault() {}});
  assert.deepEqual(JSON.parse(requests.at(-1).options.body), {answers: {topic: 'Algebra'}});
  assert.equal(get('questions').hidden, true);
  stream.emit(4, 'tool.failed', {error: 'Test failure'});
  assert.equal(get('trace').children.at(-1).className, 'failed');
  stream.emit(5, 'result', {html: '<script>bad()</script>'});
  assert.match(get('result-text').textContent, /<script>/);
  stream.emit(6, 'run.completed', {status: 'completed'});
  assert.equal(get('progress').value, 100); assert.equal(stream.closed, true);
  console.log('PASS: submit validation, task creation, trace dedup, reconnect status, progress, questions/resume, failure, inert result, stream completion');
})().catch(error => { console.error(error); process.exitCode = 1; });
