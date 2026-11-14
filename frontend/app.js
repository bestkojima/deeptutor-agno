'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {taskId: null, stream: null, seen: new Set(), questions: [], capabilities: [], busy: false};
  const eventTypes = ['run.started', 'step.started', 'step.completed', 'tool.started', 'tool.completed', 'tool.failed', 'question', 'progress', 'step.failed', 'quiz.question', 'quiz.question.started', 'quiz.question.emitted', 'quiz.question.rejected', 'quiz.question.failed', 'quiz.completed', 'reader.located', 'research.parallel.started', 'research.parallel.completed', 'solve.review', 'result', 'error', 'run.completed'];
  const stringify = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  function fail(error) { $('request-error').textContent = error.message || String(error); }
  async function request(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(stringify(payload.detail || payload.error || `Request failed (${response.status})`));
    return payload;
  }
  function clearTask() {
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
    trace(event);
    const data = event.data || {};
    switch (event.type) {
      case 'progress': {
        const percent = Number(data.percent ?? data.progress);
        if (Number.isFinite(percent)) $('progress').value = Math.max(0, Math.min(100, percent));
        $('status').textContent = data.message || data.status || 'Working…'; break;
      }
      case 'question': ask(data); break;
      case 'result': {
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
  function connect(id) {
    state.taskId = id; $('task-id').textContent = `Task ${id}`; $('connection').textContent = 'Connecting';
    const stream = new EventSource(`/api/tasks/${encodeURIComponent(id)}/events`); state.stream = stream;
    // EventSource carries Last-Event-ID on automatic reconnect; event IDs also deduplicate replay.
    stream.onmessage = consume;
    eventTypes.forEach(type => stream.addEventListener(type, message => { if (message.data) consume(message); }));
    stream.onopen = () => { $('connection').textContent = $('questions').hidden ? 'Connected' : 'Needs input'; };
    stream.onerror = message => { if (!message.data && state.stream === stream) $('connection').textContent = stream.readyState === EventSource.CLOSED ? 'Disconnected' : 'Reconnecting…'; };
  }
  $('task-form').addEventListener('submit', async event => {
    event.preventDefault(); if (state.busy) return;
    let inputs;
    try { inputs = JSON.parse($('inputs').value); if (!inputs || Array.isArray(inputs) || typeof inputs !== 'object') throw new Error('Inputs must be a JSON object.'); }
    catch (error) { fail(error); return; }
    state.busy = true; $('start').disabled = true; $('request-error').textContent = '';
    try {
      const task = await request('/api/tasks', {capability: $('capability').value, provider: $('provider').value, inputs});
      if (!task.id) throw new Error('Server did not return a task ID.');
      clearTask(); $('status').className = ''; connect(task.id);
    } catch (error) { fail(error); }
    finally { state.busy = false; $('start').disabled = false; }
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
