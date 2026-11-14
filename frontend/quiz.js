'use strict';
// Student quiz cards. Server owns scoring and permission to release feedback.
(() => {
  function create({container, request}) {
    if (!container || typeof request !== 'function') throw new Error('Quiz requires a container and request helper');
    let generation = 0, taskId = null, rows = new Map(), list, notice;
    const element = (tag, text, role) => {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = text;
      if (role) node.setAttribute('data-quiz-role', role);
      return node;
    };
    function reset() {
      generation++; taskId = null; rows = new Map();
      container.replaceChildren(); container.hidden = true;
    }
    function beginTask({taskId: id}) {
      reset();
      if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(id)) return;
      taskId = id; container.hidden = false; container.setAttribute('class', 'quiz-view');
      notice = element('p', 'Questions appear as they pass review. Submit each answer for server feedback.', 'notice');
      notice.setAttribute('role', 'status');
      list = element('div', undefined, 'items');
      container.append(element('h3', 'Practice questions'), notice, list);
    }
    function lock(row, disabled) {
      row.button.disabled = disabled;
      for (const control of row.controls) control.disabled = disabled;
    }
    function showFeedback(feedback) {
      if (!Array.isArray(feedback)) return;
      for (const entry of feedback.slice(0, 50)) {
        if (!entry || !['correct', 'incorrect', 'manual_review'].includes(entry.status)) continue;
        const row = rows.get(entry.item_id);
        if (!row) continue;
        row.submitted = true; row.busy = false; lock(row, true);
        const label = {correct: 'Correct', incorrect: 'Incorrect', manual_review: 'Manual review required (not automatically scored)'}[entry.status];
        row.feedback.replaceChildren(element('strong', label));
        if (typeof entry.explanation === 'string') row.feedback.append(element('p', entry.explanation.slice(0, 10000)));
        if (Object.prototype.hasOwnProperty.call(entry, 'correct_answer')) {
          let reference = entry.correct_answer;
          if (row.item.type === 'single_choice' && Number.isInteger(reference) && row.item.options[reference] !== undefined) reference = row.item.options[reference];
          else if (row.item.type === 'multiple_choice' && Array.isArray(reference) && reference.every(index => Number.isInteger(index) && row.item.options[index] !== undefined)) reference = reference.map(index => row.item.options[index]);
          const answer = typeof reference === 'string' ? reference : JSON.stringify(reference);
          row.feedback.append(element('p', `Reference answer: ${String(answer).slice(0, 10000)}`));
        }
      }
    }
    function addItem(raw) {
      if (!raw || typeof raw.id !== 'string' || !/^q[1-9][0-9]{0,3}$/.test(raw.id) || rows.has(raw.id) || rows.size >= 50 ||
          typeof raw.question !== 'string' || !raw.question.trim() || raw.question.length > 10000) return;
      const type = raw.type || 'single_choice';
      if (!['single_choice', 'multiple_choice', 'short_answer', 'fill_blank'].includes(type)) return;
      if (['single_choice', 'multiple_choice'].includes(type) && (!Array.isArray(raw.options) || raw.options.length < 2 || raw.options.length > 20 || raw.options.some(value => typeof value !== 'string' || value.length > 4000))) return;
      if (type === 'fill_blank' && (!Array.isArray(raw.blanks) || !raw.blanks.length || raw.blanks.length > 20 || raw.blanks.some(blank => !blank || typeof blank.id !== 'string' || !/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(blank.id)) || new Set(raw.blanks.map(blank => blank.id)).size !== raw.blanks.length)) return;
      // Copy only public fields. Ignore accidentally supplied keys/explanations.
      const item = {id: raw.id, type, question: raw.question, options: ['single_choice','multiple_choice'].includes(type) ? [...raw.options] : [], blanks: type === 'fill_blank' ? raw.blanks.map(blank => ({id: blank.id})) : []};
      const epoch = generation, ownTask = taskId;
      const card = element('section', undefined, 'item'); card.setAttribute('class', 'quiz-card');
      const form = element('form', undefined, 'form');
      const fieldset = element('fieldset'); fieldset.append(element('legend', item.question));
      const controls = [];
      if (type === 'single_choice' || type === 'multiple_choice') {
        item.options.forEach((option, index) => {
          const label = element('label'), input = element('input', undefined, 'answer');
          input.type = type === 'single_choice' ? 'radio' : 'checkbox';
          input.name = `quiz-${epoch}-${item.id}`; input.value = String(index);
          label.append(input, element('span', option)); const line = element('div'); line.append(label); fieldset.append(line); controls.push(input);
        });
      } else if (type === 'short_answer') {
        const label = element('label', 'Your answer (manual review)');
        const input = element('textarea', undefined, 'answer'); input.maxLength = 10000;
        label.append(input); fieldset.append(label); controls.push(input);
      } else {
        for (const blank of item.blanks) {
          const label = element('label', `Blank ${blank.id} (manual review)`), input = element('input', undefined, 'answer');
          input.type = 'text'; input.maxLength = 2000; input.name = blank.id;
          label.append(input); fieldset.append(label); controls.push(input);
        }
      }
      const button = element('button', 'Submit answer', 'submit'); button.type = 'submit';
      const feedback = element('div', undefined, 'feedback'); feedback.setAttribute('role', 'status');
      form.append(fieldset, button); card.append(form, feedback); list.append(card);
      const row = {item, controls, button, feedback, submitted: false, busy: false}; rows.set(item.id, row);
      form.addEventListener('submit', async event => {
        event.preventDefault();
        if (epoch !== generation || ownTask !== taskId || row.busy || row.submitted) return;
        let value;
        if (type === 'single_choice' || type === 'multiple_choice') {
          const selected = controls.map((control, index) => control.checked ? index : null).filter(index => index !== null);
          if (!selected.length || (type === 'single_choice' && selected.length !== 1)) {
            feedback.replaceChildren(element('p', 'Select an answer before submitting.')); return;
          }
          value = type === 'single_choice' ? selected[0] : selected;
        } else if (type === 'short_answer') value = controls[0].value;
        else value = Object.fromEntries(item.blanks.map((blank, index) => [blank.id, controls[index].value]));
        row.busy = true; lock(row, true); feedback.replaceChildren(element('p', 'Submitting to server…'));
        try {
          let response = await request(`/api/tasks/${encodeURIComponent(ownTask)}/quiz/submit`, {answers: {[item.id]: value}});
          if (response && typeof response.json === 'function') {
            if (!response.ok) throw new Error('Request failed');
            response = await response.json();
          }
          if (epoch !== generation || ownTask !== taskId) return;
          if (!response || !Array.isArray(response.feedback) || !response.feedback.some(entry => entry && entry.item_id === item.id && ['correct','incorrect','manual_review'].includes(entry.status))) throw new Error('Feedback missing');
          showFeedback(response.feedback);
        } catch (_) {
          if (epoch !== generation || ownTask !== taskId) return;
          row.busy = false; lock(row, false);
          feedback.replaceChildren(element('p', 'Could not submit this answer. Try again.'));
        }
      });
    }
    function handleEvent(event) {
      if (!taskId || !event || (event.task_id && event.task_id !== taskId)) return;
      const data = event.data || {};
      if (event.type === 'quiz.question.emitted') addItem(data.item);
      else if (event.type === 'quiz.question') addItem(data);
      else if (event.type === 'result') {
        if (Array.isArray(data.items)) for (const item of data.items.slice(0, 50)) addItem(item);
        showFeedback(data.feedback);
        if (data.quiz_status?.status === 'partial') notice.textContent = 'Some questions failed. Accepted questions remain available.';
        else if (data.quiz_status?.status === 'failed') notice.textContent = 'Generation stopped. Any accepted questions remain available.';
        else if (data.quiz_status?.status === 'completed') notice.textContent = 'Quiz generation complete. Submit your answers for feedback.';
      } else if (event.type === 'quiz.question.failed' || event.type === 'error') {
        notice.textContent = 'A generation step failed. Accepted questions remain available.';
      }
    }
    reset();
    return {beginTask, handleEvent, reset};
  }
  globalThis.TutorQuiz = {create};
})();
