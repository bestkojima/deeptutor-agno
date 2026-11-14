'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {taskId: null, stream: null, seen: new Set(), questions: [], capabilities: [], busy: false};
  const eventTypes = ['run.started', 'step.started', 'step.completed', 'tool.started', 'tool.completed', 'tool.failed', 'question', 'progress', 'step.failed', 'quiz.question', 'quiz.question.started', 'quiz.question.emitted', 'quiz.question.rejected', 'quiz.question.failed', 'quiz.completed', 'reader.located', 'research.parallel.started', 'research.parallel.completed', 'research.interrupted', 'research.checkpoint.reused', 'research.checkpoint.retained', 'video.revision.started', 'solve.review', 'result', 'error', 'run.completed'];
  const stringify = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  function fail(error) { $('request-error').textContent = error.message || String(error); }
  async function request(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(stringify(payload.detail || payload.error || `Request failed (${response.status})`));
    return payload;
  }
  const reader = globalThis.TutorReader?.create({container: $('reader-workspace')});
  const quiz = globalThis.TutorQuiz?.create({container: $('quiz-workspace'), request});
  // Function graphs use numeric API data only. Model/API SVG strings never enter the DOM.
  let plotRevision = 0;
  let plotSpec = null;
  let plotYRange = null;
  function clearPlot() {
    plotRevision++;
    plotSpec = null; plotYRange = null;
    $('visualization').hidden = true;
    $('visualization-plot').replaceChildren();
    $('plot-controls').replaceChildren();
    $('plot-status').textContent = '';
    $('plot-equation').textContent = '';
  }
  const finiteNumber = value => typeof value === 'number' && Number.isFinite(value);
  function validatePlot(visual) {
    const domain = visual?.content?.domain, curves = visual?.computed?.curves, range = visual?.computed?.y_range;
    if (visual?.type !== 'function_graph' || !Array.isArray(domain) || domain.length !== 2 ||
        !domain.every(v => finiteNumber(v) && Math.abs(v) <= 10000) || domain[1] - domain[0] < 1e-6 ||
        !Array.isArray(range) || range.length !== 2 || !range.every(v => finiteNumber(v) && Math.abs(v) <= 2e15) || range[1] <= range[0] ||
        !Array.isArray(curves) || curves.length < 1 || curves.length > 8) throw new Error('Invalid function graph data.');
    for (const curve of curves) {
      if (!Array.isArray(curve.points) || curve.points.length < 2 || curve.points.length > 501 ||
          curve.points.some((point, i) => !Array.isArray(point) || point.length !== 2 ||
            !point.every(finiteNumber) || Math.abs(point[1]) > 1e15 || point[0] < domain[0] || point[0] > domain[1] ||
            (i > 0 && point[0] <= curve.points[i - 1][0]))) throw new Error('Invalid function graph points.');
    }
    return {domain, curves, range};
  }
  function svgNode(tag, attrs = {}, text) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function drawPlot(visual) {
    const {domain, curves, range} = validatePlot(visual);
    // Keep the initial vertical scale while dragging, so coefficient changes remain visible.
    const [ymin, ymax] = plotYRange || range;
    const [xmin, xmax] = domain;
    const coordinate = value => {
      if (!Number.isFinite(value) || Math.abs(value) > 1e20) throw new Error('Invalid plot coordinate range.');
      return value;
    };
    const x = value => coordinate(60 + (value - xmin) / (xmax - xmin) * 560);
    const y = value => coordinate(300 - (value - ymin) / (ymax - ymin) * 270);
    const svg = svgNode('svg', {viewBox: '0 0 680 350', role: 'img', 'aria-label': 'Server-computed function graph'});
    svg.append(svgNode('title', {}, 'Function graph: x horizontal, y vertical'));
    svg.append(svgNode('rect', {width: 680, height: 350, fill: '#ffffff'}));
    const defs = svgNode('defs'), clip = svgNode('clipPath', {id: 'function-plot-bounds'});
    clip.append(svgNode('rect', {x: 60, y: 30, width: 560, height: 270})); defs.append(clip); svg.append(defs);
    for (let i = 0; i <= 4; i++) {
      const vx = xmin + (xmax - xmin) * i / 4, vy = ymin + (ymax - ymin) * i / 4;
      svg.append(svgNode('line', {x1: x(vx), x2: x(vx), y1: 30, y2: 300, stroke: '#dde4ed'}));
      svg.append(svgNode('line', {x1: 60, x2: 620, y1: y(vy), y2: y(vy), stroke: '#dde4ed'}));
      svg.append(svgNode('text', {x: x(vx), y: 320, 'text-anchor': 'middle', fill: '#15213a', 'font-size': 11}, String(Number(vx.toPrecision(4)))));
      svg.append(svgNode('text', {x: 55, y: y(vy) + 4, 'text-anchor': 'end', fill: '#15213a', 'font-size': 11}, String(Number(vy.toPrecision(4)))));
    }
    if (xmin <= 0 && xmax >= 0) svg.append(svgNode('line', {x1: x(0), x2: x(0), y1: 30, y2: 300, stroke: '#526079'}));
    if (ymin <= 0 && ymax >= 0) svg.append(svgNode('line', {x1: 60, x2: 620, y1: y(0), y2: y(0), stroke: '#526079'}));
    const colors = ['#315cf6', '#c13570', '#14804a', '#995a00'];
    curves.forEach((curve, i) => svg.append(svgNode('polyline', {
      points: curve.points.map(([vx, vy]) => `${x(vx).toFixed(2)},${y(vy).toFixed(2)}`).join(' '),
      fill: 'none', stroke: colors[i % colors.length], 'stroke-width': 2, 'clip-path': 'url(#function-plot-bounds)'
    })));
    svg.append(svgNode('text', {x: 640, y: 320, fill: '#15213a'}, 'x'));
    svg.append(svgNode('text', {x: 24, y: 24, fill: '#15213a'}, 'y'));
    $('visualization-plot').replaceChildren(svg);
    if (!plotYRange) plotYRange = [...range];
    const curve = visual.content.curves?.[0];
    $('plot-equation').textContent = curve?.function === 'quadratic' && visual.content.curves.length === 1
      ? `Displayed: y = ${curve.parameters.a}x² + (${curve.parameters.b})x + (${curve.parameters.c})`
      : 'Server-computed sampled curves';
  }
  function showPlot(visual) {
    clearPlot();
    if (visual?.type !== 'function_graph') return;
    $('visualization').hidden = false;
    try {
      drawPlot(visual);
      const curve = visual.content.curves?.[0];
      if (visual.content.curves?.length !== 1 || curve.function !== 'quadratic') {
        $('plot-status').textContent = 'Static graph. Coefficient sliders support one quadratic curve.'; return;
      }
      const parameters = curve.parameters;
      if (!parameters || !['a', 'b', 'c'].every(key => finiteNumber(parameters[key]) && Math.abs(parameters[key]) <= 1e6))
        throw new Error('Invalid quadratic parameters.');
      plotSpec = {domain: [...visual.content.domain], samples: visual.computed.curves[0].points.length,
        curves: [{function: 'quadratic', parameters: {...parameters}}]};
      for (const key of ['a', 'b', 'c']) {
        const label = document.createElement('label'); label.htmlFor = `coefficient-${key}`;
        label.textContent = `${key} coefficient`;
        const input = document.createElement('input'); input.id = `coefficient-${key}`; input.type = 'range';
        input.min = String(Math.min(-10, parameters[key])); input.max = String(Math.max(10, parameters[key]));
        input.step = 'any'; input.value = String(parameters[key]);
        const output = document.createElement('output'); output.id = `coefficient-${key}-value`; output.textContent = input.value;
        input.addEventListener('input', updatePlot);
        $('plot-controls').append(label, input, output);
      }
      $('plot-status').textContent = 'Drag a coefficient. Samples update on the server, without a model call. Vertical scale stays fixed.';
    } catch (error) {
      $('visualization-plot').replaceChildren(); $('plot-controls').replaceChildren();
      $('plot-status').textContent = error.message;
    }
  }
  async function updatePlot() {
    const revision = ++plotRevision;
    if (!plotSpec) return;
    const parameters = {};
    try {
      for (const key of ['a', 'b', 'c']) {
        const raw = $(`coefficient-${key}`).value;
        const value = Number(raw);
        if (!raw.trim() || !Number.isFinite(value) || Math.abs(value) > 1e6) throw new Error('Enter finite coefficients within ±1000000.');
        parameters[key] = value;
        $(`coefficient-${key}-value`).textContent = String(value);
      }
      const spec = {...plotSpec, curves: [{function: 'quadratic', parameters}]};
      $('plot-status').textContent = 'Updating samples… Previous graph shown until ready.';
      const result = await request('/api/visualize/plot', spec);
      if (revision !== plotRevision) return;
      validatePlot(result);
      const returned = result.content.curves?.[0];
      if (result.content.curves?.length !== 1 || returned?.function !== 'quadratic' ||
          !['a', 'b', 'c'].every(key => returned.parameters?.[key] === parameters[key])) throw new Error('Invalid plot response parameters.');
      drawPlot(result);
      plotSpec = spec;
      $('plot-status').textContent = 'Updated from backend samples. Fixed vertical scale; curves outside the window are clipped.';
    } catch (error) {
      if (revision === plotRevision) $('plot-status').textContent = `${error.message} Last valid graph retained.`;
    }
  }
  function clearTask() {
    reader?.reset(); quiz?.reset();
    if ($('research-resume')) $('research-resume').hidden = true;
    clearPlot();
    if (state.stream) state.stream.close();
    state.stream = null; state.seen.clear(); state.questions = [];
    $('trace').replaceChildren(); $('trace-empty').hidden = false; $('event-count').textContent = '0 events';
    $('questions').hidden = true; $('result').hidden = true; $('result-text').textContent = '';
    $('lesson-media')?.replaceChildren();
    $('progress').value = 0; $('request-error').textContent = '';
  }
  function trace(event) {
    const row = document.createElement('li');
    if (/failed|error/.test(event.type)) row.className = 'failed';
    else if (/completed|result/.test(event.type)) row.className = 'success';
    const title = document.createElement('div'); title.className = 'event-title';
    const label = document.createElement('span'); label.textContent = event.type + ((event.data?.tool || event.data?.name) ? ` · ${event.data.tool || event.data.name}` : '');
    const time = document.createElement('span'); time.className = 'event-time';
    time.textContent = event.created_at ? new Date(event.created_at).toLocaleTimeString() : '';
    title.append(label, time); row.append(title);
    const details = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = 'Event details';
    const body = document.createElement('pre'); body.textContent = stringify(event.data ?? {});
    details.append(summary, body); row.append(details); $('trace').append(row);
    $('trace-empty').hidden = true; $('event-count').textContent = `${$('trace').children.length} events`;
  }
  function ask(data) {
    const questions = data.questions || [data];
    state.questions = questions.map((q, i) => typeof q === 'string' ? {id: String(i), question: q} : q);
    $('question-fields').replaceChildren();
    state.questions.forEach((q, i) => {
      const label = document.createElement('label'); label.htmlFor = `answer-${i}`;
      label.textContent = q.question || q.text || q.prompt || q.id || 'Your answer';
      let input;
      if (Array.isArray(q.options) && q.options.length) {
        input = document.createElement('select');
        const empty = document.createElement('option'); empty.value = ''; empty.textContent = 'Choose an answer'; input.append(empty);
        q.options.forEach(option => { const item = document.createElement('option'); item.value = typeof option === 'string' ? option : option.value; item.textContent = typeof option === 'string' ? option : option.label || option.value; input.append(item); });
      } else { input = document.createElement('textarea'); input.rows = 2; }
      input.id = `answer-${i}`; input.required = q.required !== false;
      $('question-fields').append(label, input);
    });
    $('questions').hidden = false; $('resume').disabled = false;
    $('status').textContent = 'Waiting for your answers'; $('connection').textContent = 'Needs input';
  }
  function consume(message) {
    let event;
    try { event = JSON.parse(message.data); } catch { fail(new Error('An unreadable event was received. Reconnect to replay this task.')); return; }
    if (!event || typeof event !== 'object' || !event.type) return;
    const id = String(event.id ?? message.lastEventId ?? '');
    if (id && state.seen.has(id)) return;
    if (id) state.seen.add(id);
    trace(event); reader?.handleEvent(event); quiz?.handleEvent(event);
    const data = event.data || {};
    switch (event.type) {
      case 'progress': {
        const percent = Number(data.percent ?? data.progress);
        if (Number.isFinite(percent)) $('progress').value = Math.max(0, Math.min(100, percent));
        $('status').textContent = data.message || data.status || 'Working…'; break;
      }
      case 'question': ask(data); break;
      case 'research.interrupted':
        $('status').textContent = 'Research interrupted. Resume to reuse finished evidence.';
        if ($('research-resume')) $('research-resume').hidden = false;
        state.stream?.close(); state.stream = null; break;
      case 'result': {
        showPlot(data.visualization);
        $('result').hidden = false;
        $('result-text').textContent = stringify(data);
        const media = $('lesson-media');
        if (media) {
          media.replaceChildren();
          const video = data.video_url, captions = data.subtitles_url;
          if (typeof video === 'string' && typeof captions === 'string' &&
              /^\/api\/media\/[a-f0-9]{32}\/lesson\.mp4$/.test(video) &&
              captions === video.replace(/lesson\.mp4$/, 'captions.vtt')) {
            const player = document.createElement('video');
            player.controls = true; player.preload = 'metadata'; player.src = video;
            player.style.maxWidth = '100%';
            const track = document.createElement('track');
            track.kind = 'subtitles'; track.label = '字幕'; track.src = captions;
            player.append(track); media.append(player);
          }
        }
        break;
      }
      case 'error': $('status').textContent = data.message || data.error || 'Task failed'; $('status').className = 'error'; break;
      case 'run.started': $('status').textContent = 'Running'; $('status').className = ''; break;
      case 'run.completed':
        $('questions').hidden = true;
        if (!['failed', 'error'].includes(data.status)) { $('progress').value = 100; $('status').textContent = 'Completed'; }
        else $('status').textContent = 'Failed';
        $('connection').textContent = data.status === 'failed' ? 'Failed' : 'Finished';
        state.stream?.close(); state.stream = null; break;
    }
  }
  function connect(id, after = 0) {
    state.taskId = id; $('task-id').textContent = `Task ${id}`; $('connection').textContent = 'Connecting';
    const stream = new EventSource(`/api/tasks/${encodeURIComponent(id)}/events${after ? '?after=' + after : ''}`); state.stream = stream;
    // EventSource carries Last-Event-ID on automatic reconnect; event IDs also deduplicate replay.
    stream.onmessage = consume;
    eventTypes.forEach(type => stream.addEventListener(type, message => { if (message.data) consume(message); }));
    stream.onopen = () => { $('connection').textContent = $('questions').hidden ? 'Connected' : 'Needs input'; };
    stream.onerror = message => { if (!message.data && state.stream === stream) $('connection').textContent = stream.readyState === EventSource.CLOSED ? 'Disconnected' : 'Reconnecting…'; };
  }
  $('plot-example').addEventListener('click', async () => {
    clearPlot();
    const revision = plotRevision;
    $('visualization').hidden = false;
    $('plot-status').textContent = 'Loading backend samples…';
    try {
      const visual = await request('/api/visualize/plot', {domain: [-5, 5], samples: 101,
        curves: [{function: 'quadratic', parameters: {a: 1, b: 0, c: 0}}]});
      if (revision === plotRevision) showPlot(visual);
    } catch (error) {
      if (revision === plotRevision) $('plot-status').textContent = error.message;
    }
  });
  $('task-form').addEventListener('submit', async event => {
    event.preventDefault(); if (state.busy) return;
    let inputs;
    try { inputs = JSON.parse($('inputs').value); if (!inputs || Array.isArray(inputs) || typeof inputs !== 'object') throw new Error('Inputs must be a JSON object.'); }
    catch (error) { fail(error); return; }
    state.busy = true; $('start').disabled = true; $('request-error').textContent = '';
    try {
      const task = await request('/api/tasks', {capability: $('capability').value, provider: $('provider').value, inputs});
      if (!task.id) throw new Error('Server did not return a task ID.');
      clearTask(); $('status').className = '';
      if (['immersive_reading','reading'].includes($('capability').value)) reader?.beginTask({taskId: task.id, sources: inputs.sources});
      if ($('capability').value === 'quiz') quiz?.beginTask({taskId: task.id});
      connect(task.id);
    } catch (error) { fail(error); }
    finally { state.busy = false; $('start').disabled = false; }
  });
  async function resumeResearch(taskId, after) {
    await request(`/api/tasks/${encodeURIComponent(taskId)}/resume`, {answers: {}});
    if ($('research-resume')) $('research-resume').hidden = true;
    state.stream?.close();
    connect(taskId, after);
  }
  $('research-resume')?.addEventListener('click', async () => {
    if (!state.taskId) return;
    try { await resumeResearch(state.taskId, Math.max(0, ...[...state.seen].map(Number).filter(Number.isFinite))); }
    catch (error) { fail(error); }
  });
  $('research-reopen')?.addEventListener('submit', async event => {
    event.preventDefault();
    const id = $('research-task-id').value.trim();
    if (!/^[a-f0-9]{32}$/.test(id)) { fail(new Error('Enter a valid research task ID.')); return; }
    try {
      const status = await request(`/api/tasks/${id}`);
      if (!status.can_resume_research) throw new Error('That task is not recoverable confirmed research.');
      await request(`/api/tasks/${id}/resume`, {answers: {}});
      clearTask(); connect(id, status.last_event_id);
    } catch (error) { fail(error); }
  });
  $('answers-form').addEventListener('submit', async event => {
    event.preventDefault(); if ($('resume').disabled) return;
    const taskId = state.taskId; const answers = {};
    state.questions.forEach((q, i) => { answers[q.id ?? String(i)] = $(`answer-${i}`).value; });
    $('resume').disabled = true; $('request-error').textContent = '';
    // Hide before sending so a fast next question event is not hidden by the response.
    $('questions').hidden = true;
    try { await request(`/api/tasks/${encodeURIComponent(taskId)}/resume`, {answers}); }
    catch (error) { if (state.taskId === taskId) { $('questions').hidden = false; $('resume').disabled = false; fail(error); } }
  });
  function describeCapability() {
    const capability = state.capabilities.find(item => (item.id || item.name) === $('capability').value);
    $('capability-description').textContent = capability?.description || '';
  }
  $('capability').addEventListener('change', describeCapability);
  request('/api/capabilities').then(response => {
    state.capabilities = (Array.isArray(response) ? response : response.capabilities || []).map(item => typeof item === 'string' ? {id: item} : item);
    for (const option of $('provider').children) {
      const provider = response.providers?.[option.value];
      if (provider && !provider.available) { option.disabled = true; option.textContent += ` · unavailable: ${provider.reason || 'not configured'}`; }
    }
    $('capability').replaceChildren();
    state.capabilities.forEach(item => {
      if (typeof item === 'string') item = {id: item};
      const option = document.createElement('option'); option.value = item.id || item.name; option.textContent = item.label || item.name || item.id; $('capability').append(option);
    });
    $('start').disabled = !state.capabilities.length; describeCapability();
    if (!state.capabilities.length) throw new Error('No capabilities are available.');
  }).catch(fail);
})();
