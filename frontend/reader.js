'use strict';
// Supplied-source reader only. No source URL discovery, HTML parsing, or PDF claims.
(() => {
  const MEDIA = /^\/api\/media\/[a-f0-9]{32}\/lesson\.mp4$/;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const stamp = seconds => {
    const millis = Math.round(seconds * 1000);
    const minutes = Math.floor(millis / 60000), wholeSeconds = Math.floor(millis % 60000 / 1000);
    const fraction = String(millis % 1000).padStart(3, '0').replace(/0+$/, '');
    return `${String(minutes).padStart(2, '0')}:${String(wholeSeconds).padStart(2, '0')}${fraction ? `.${fraction}` : ''}`;
  };
  function create({container}) {
    let generation = 0, taskId = null, sources = new Map(), references = new Set(), entries = new Map();
    let list, location, message, media;
    const element = (tag, text, role) => {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = text;
      if (role) node.setAttribute('data-reader-role', role);
      return node;
    };
    const locator = source => [
      source.page != null ? `Page ${source.page} excerpt` : '',
      source.start_seconds != null ? `Caption ${stamp(source.start_seconds)}${source.end_seconds != null ? `–${stamp(source.end_seconds)}` : ''}` : ''
    ].filter(Boolean).join(' · ') || 'Supplied text excerpt';
    function stopMedia() {
      if (media) {
        for (const child of media.children) if (child.tagName === 'VIDEO') child.pause();
        media.replaceChildren();
      }
    }
    function reset() {
      stopMedia();
      generation++; taskId = null; sources = new Map(); entries = new Map(); references = new Set();
      container.replaceChildren(); container.hidden = true;
    }
    function beginTask({taskId: id, sources: supplied}) {
      reset();
      if (typeof id !== 'string' || !id) return;
      taskId = id;
      if (!Array.isArray(supplied) || !supplied.length) return;
      const counts = new Map();
      for (const row of supplied) if (row && typeof row.id === 'string') counts.set(row.id, (counts.get(row.id) || 0) + 1);
      let total = 0, skipped = 0;
      for (const row of supplied) {
        if (!row || typeof row.id !== 'string' || !row.id || counts.get(row.id) !== 1 ||
            typeof row.text !== 'string' || !row.text || sources.size >= 200 || row.text.length > 100000 ||
            total + row.text.length > 2000000 ||
            (row.page != null && (!Number.isInteger(row.page) || row.page < 1)) ||
            (row.start_seconds != null && (!finite(row.start_seconds) || row.start_seconds < 0 || row.start_seconds > 1e9)) ||
            (row.end_seconds != null && (!finite(row.end_seconds) || row.end_seconds > 1e9 || !finite(row.start_seconds) || row.end_seconds < row.start_seconds))) {
          skipped++; continue;
        }
        const source = {id: row.id, text: row.text, title: typeof row.title === 'string' ? row.title : row.id};
        for (const key of ['page', 'start_seconds', 'end_seconds']) if (row[key] != null) source[key] = row[key];
        if (typeof row.media_url === 'string' && MEDIA.test(row.media_url)) source.media_url = row.media_url;
        sources.set(row.id, source); total += row.text.length;
      }
      container.hidden = false; container.setAttribute('class', 'reader-view');
      container.append(element('h3', 'Read supplied sources'));
      container.append(element('p', 'Page excerpts and caption previews, not a PDF viewer or full transcript. Only literal quote matches are highlighted.'));
      location = element('p', 'Choose a citation to locate its supplied excerpt.', 'location'); location.setAttribute('role', 'status');
      message = element('p', skipped ? `${skipped} invalid, duplicate or oversized source entries omitted.` : '', 'message'); message.setAttribute('role', 'status');
      list = element('ol', undefined, 'citations');
      media = element('div', undefined, 'media');
      container.append(location, message, list, media);
      const excerpts = element('div', undefined, 'excerpts');
      for (const source of sources.values()) {
        const article = element('article');
        article.append(element('h4', `${source.title} · ${locator(source)}`));
        const text = element('p', source.text, 'excerpt'); text.tabIndex = -1;
        text.id = `reader-excerpt-${generation}-${entries.size}`;
        article.append(text); excerpts.append(article); entries.set(source.id, text);
      }
      container.append(excerpts);
      if (!sources.size) message.textContent = 'No valid supplied excerpts are available for navigation.';
    }
    function checked(reference) {
      if (!reference || typeof reference !== 'object') return null;
      const source = sources.get(reference.source_id);
      if (!source || typeof reference.quote !== 'string' || !reference.quote.trim() || !source.text.includes(reference.quote)) return null;
      for (const key of ['page', 'start_seconds', 'end_seconds']) {
        if (reference[key] != null && reference[key] !== source[key]) return null;
      }
      return source;
    }
    function navigate(reference, expectedGeneration) {
      if (expectedGeneration !== generation) return;
      const source = checked(reference);
      if (!source) { message.textContent = 'Reference unavailable: no exact match in this task’s supplied sources.'; return; }
      for (const [id, text] of entries) text.replaceChildren(element('span', sources.get(id).text));
      const target = entries.get(source.id), start = source.text.indexOf(reference.quote);
      target.replaceChildren(element('span', source.text.slice(0, start)), element('mark', reference.quote), element('span', source.text.slice(start + reference.quote.length)));
      location.textContent = `${source.title} · ${locator(source)}`;
      message.textContent = 'Highlighted the first literal occurrence in the supplied excerpt.';
      target.scrollIntoView?.({block: 'center', behavior: 'auto'}); target.focus?.({preventScroll: true});
      stopMedia();
      if (source.media_url && finite(source.start_seconds)) {
        const player = element('video', undefined, 'player'); player.controls = true; player.preload = 'metadata';
        const seek = () => {
          if (generation !== expectedGeneration || media.children[0] !== player) return;
          if (!finite(player.duration) || source.start_seconds > player.duration) {
            message.textContent = 'Caption located. Timestamp is outside the available media duration; playback was not moved.'; return;
          }
          try { player.currentTime = source.start_seconds; }
          catch { message.textContent = 'Caption located. Media seeking is unavailable.'; }
        };
        player.addEventListener('loadedmetadata', seek);
        player.addEventListener('error', () => {
          if (generation === expectedGeneration && media.children[0] === player) message.textContent = 'Media unavailable. The supplied caption excerpt remains available.';
        });
        player.src = source.media_url;
        media.append(player, element('p', 'Local lesson media. Seeking does not start playback.'));
      }
    }
    function addReference(reference) {
      const source = checked(reference);
      if (!source) {
        if (message) message.textContent = 'Reference unavailable: source, literal quote or supplied page/time does not match. No navigation performed.';
        return;
      }
      const key = JSON.stringify([source.id, reference.quote]);
      if (references.has(key) || references.size >= 500) return;
      references.add(key);
      const snapshot = {source_id: source.id, quote: reference.quote};
      const version = generation;
      const row = element('li');
      const link = element('a', `${source.title} · ${locator(source)}: “${reference.quote}”`, 'citation-link');
      // Fragment names are generated locally, never copied from source URLs or model output.
      link.href = `#${entries.get(source.id).id}`;
      link.addEventListener('click', event => { event.preventDefault(); navigate(snapshot, version); });
      row.append(link); list.append(row);
    }
    function handleEvent(event) {
      if (!taskId || !event || event.task_id !== taskId || !list || container.hidden) return;
      if (event.type === 'reader.located') addReference(event.data);
      if (event.type === 'result' && Array.isArray(event.data?.citations)) event.data.citations.slice(0, 500).forEach(addReference);
    }
    reset();
    return {beginTask, handleEvent, reset};
  }
  globalThis.TutorReader = Object.freeze({create});
})();
