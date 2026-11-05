/* Administrator-only review of submitted files. Source is always rendered as inert text. */
(() => {
  'use strict';
  const root = document.getElementById('ide-history');
  if (!root) return;
  const element = id => document.getElementById('history-' + id);
  const controllers = new Set(), replayControllers = new Set();
  let files = [], nextBefore = null, selectedFile = null, timeline = null, visiblePoints = [], index = -1;
  let generation = 0, seekGeneration = 0, playbackGeneration = 0, playing = false, timer = null, markerLimit = 100, busy = false;
  const status = text => { element('status').textContent = text; };
  const number = value => Math.max(0, Number(value) || 0).toLocaleString();
  function timestamp(value) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? '' : date.toLocaleString(); }
  function elapsed(value) { const seconds = Math.max(0, Math.floor((Number(value) || 0) / 1000)); return seconds >= 3600 ? Math.floor(seconds / 3600) + 'h ' + Math.floor(seconds % 3600 / 60) + 'm' : seconds >= 60 ? Math.floor(seconds / 60) + 'm ' + seconds % 60 + 's' : seconds + 's'; }
  function pause() { playbackGeneration++; playing = false; clearTimeout(timer); timer = null; element('play').textContent = 'Play'; }
  function abort(set) { for (const controller of set) controller.abort(); set.clear(); }
  function invalidate() { pause(); generation++; seekGeneration++; abort(controllers); abort(replayControllers); busy = false; element('load').disabled = false; element('more').disabled = false; }
  function query() { return new URLSearchParams({userId: element('participant').value, taskId: element('task').value}); }
  async function request(suffix, params, replay = false) {
    const controller = new AbortController(), set = replay ? replayControllers : controllers;
    set.add(controller);
    try {
      const response = await fetch(root.dataset.api + '/' + suffix + '?' + params, {credentials:'same-origin', cache:'no-store', redirect:'error', signal:controller.signal});
      if (!response.ok) {
        const value = await response.json().catch(() => null), message = value?.error?.message;
        throw Error(typeof message === 'string' ? message : 'History request failed (' + response.status + ')');
      }
      return await response.json();
    } finally { set.delete(controller); }
  }
  function notice(values, unavailable = false) {
    const text = [...new Set(values.filter(value => typeof value === 'string' && value))].join('\n');
    element('notices').textContent = text; element('notes').hidden = !text;
    element('notes-summary').textContent = timeline?.partial ? 'Some earlier activity is unavailable — details' : unavailable ? 'This source position is unavailable — details' : 'Recording notes';
    if (!text) element('notes').open = false;
  }
  function clearSource() { element('source').value = ''; element('before').value = ''; element('before-status').textContent = ''; }
  function clearPlayback() {
    timeline = null; visiblePoints = []; index = -1; markerLimit = 100; clearSource();
    for (const id of ['activity','markers']) element(id).replaceChildren();
    for (const id of ['filename','submission','correlation','summary','event','marker-count','thresholds']) element(id).textContent = '';
    element('notes').open = false; notice([]); element('player').hidden = true; element('empty').hidden = false;
    element('empty').textContent = 'Select a submitted file to review its writing history.';
    element('more-markers').hidden = true; element('timeline').value = '0'; element('timeline').max = '0';
  }
  function updateButtons() {
    element('previous').disabled = busy || index <= 0;
    element('next').disabled = busy || index < 0 || index >= visiblePoints.length - 1;
    element('play').disabled = !visiblePoints.length;
  }
  function pointLabel(point, position) {
    const kind = point.kind === 'initial' ? 'Starting snapshot' : point.kind === 'submission' ? 'Submission snapshot' : 'Editing period';
    const period = timeline?.periods?.find(row => row.sessionId === point.sessionId);
    return kind + (point.kind === 'editing' ? ' ' + (position + 1) : '') + ' · ' + (timestamp(point.timestamp) || elapsed(point.offsetMs)) + (period?.label ? ' · ' + period.label : '');
  }
  function describePoint(point) {
    const changes = [];
    if (point.editCount) changes.push(number(point.editCount) + (Number(point.editCount) === 1 ? ' edit' : ' edits'));
    if (point.inserted) changes.push('+' + number(point.inserted) + ' characters');
    if (point.deleted) changes.push('−' + number(point.deleted) + ' characters');
    if (point.keyboardInputs) changes.push(number(point.keyboardInputs) + ' key-linked edits');
    return changes.join(' · ');
  }
  function markCurrent() {
    element('timeline').value = String(Math.max(0, index));
    for (const button of element('activity').querySelectorAll('button')) button.classList.toggle('is-current', Number(button.dataset.index) === index);
  }
  function renderActivity() {
    const limit = 240, sample = visiblePoints.length <= limit ? visiblePoints.map((_, position) => position) : Array.from({length:limit}, (_, position) => Math.round(position * (visiblePoints.length - 1) / (limit - 1)));
    const max = visiblePoints.reduce((value, point) => Math.max(value, Number(point.inserted || 0) + Number(point.deleted || 0)), 1);
    element('activity').replaceChildren(...sample.map(position => {
      const point = visiblePoints[position], button = document.createElement('button');
      button.type = 'button'; button.dataset.index = String(position);
      button.style.height = Math.max(12, Math.round(64 * Math.log2(2 + Number(point.inserted || 0) + Number(point.deleted || 0)) / Math.log2(2 + max))) + 'px';
      button.classList.toggle('has-marker', !!point.markers?.length); button.classList.toggle('is-boundary', point.kind !== 'editing');
      button.setAttribute('aria-label', pointLabel(point, position) + (point.markers?.length ? ' · review marker' : ''));
      button.title = pointLabel(point, position) + (describePoint(point) ? '\n' + describePoint(point) : '');
      button.addEventListener('click', () => void seek(position)); return button;
    }));
    markCurrent();
  }
  function renderMarkers() {
    const rows = [];
    for (const point of timeline?.points || []) for (const marker of point.markers || []) rows.push({point, marker});
    element('marker-count').textContent = '(' + number(rows.length) + ')';
    if (!rows.length) {
      const empty = document.createElement('p'); empty.className = 'history-muted'; empty.textContent = 'No review rule matched the retained activity. This is not an authorship assessment.';
      element('markers').replaceChildren(empty); element('more-markers').hidden = true; return;
    }
    element('markers').replaceChildren(...rows.slice(0, markerLimit).map(({point, marker}) => {
      const row = document.createElement('div'), button = document.createElement('button'), description = document.createElement('p'), time = document.createElement('small');
      row.className = 'history-marker-row'; button.type = 'button'; button.textContent = marker.label || 'Review activity'; button.dataset.kind = marker.kind || '';
      description.textContent = marker.detail || 'Inspect the recorded activity in context.'; time.textContent = timestamp(point.timestamp) || elapsed(point.offsetMs); description.append(time);
      button.addEventListener('click', () => {
        let position = visiblePoints.findIndex(candidate => candidate.id === point.id);
        if (position < 0) { element('marked-only').checked = false; rebuildPoints(point.id); position = visiblePoints.findIndex(candidate => candidate.id === point.id); }
        if (position >= 0) void seek(position);
      });
      row.append(button, description); return row;
    }));
    element('more-markers').hidden = rows.length <= markerLimit;
    if (rows.length > markerLimit) element('more-markers').textContent = 'Show more markers (' + number(rows.length - markerLimit) + ' remaining)';
  }
  function rebuildPoints(preferred) {
    const all = timeline?.points || [];
    visiblePoints = element('marked-only').checked ? all.filter(point => point.kind !== 'editing' || point.markers?.length) : all;
    index = preferred ? visiblePoints.findIndex(point => point.id === preferred) : -1;
    if (index < 0) index = 0;
    element('timeline').max = String(Math.max(0, visiblePoints.length - 1));
    renderActivity(); updateButtons();
  }
  function renderFiles() {
    element('files').replaceChildren(...files.map(file => {
      const card = document.createElement('div'), button = document.createElement('button'), info = document.createElement('p'), link = document.createElement('a');
      card.className = 'history-file-card'; card.classList.toggle('is-selected', selectedFile?.fileId === file.fileId); card.dataset.fileId = String(file.fileId);
      button.type = 'button'; button.className = 'history-file-select'; button.textContent = file.sourceFilename || file.filename; button.setAttribute('aria-pressed', String(selectedFile?.fileId === file.fileId)); button.dataset.fileId = String(file.fileId);
      button.addEventListener('click', () => void chooseFile(file));
      info.textContent = timestamp(file.submittedAt) + (file.language ? ' · ' + file.language : '');
      link.href = root.dataset.submission + '/' + encodeURIComponent(file.submissionId); link.textContent = 'Submission #' + file.submissionId;
      card.append(button, info, link);
      if (!file.hasHistory) { const unavailable = document.createElement('p'); unavailable.className = 'history-file-unavailable'; unavailable.textContent = 'History unavailable'; card.append(unavailable); }
      element('file-count').textContent = number(files.length) + (files.length === 1 ? ' submitted file' : ' submitted files');
      return card;
    }));
    if (!files.length) element('file-count').textContent = 'No files have been submitted to this problem.';
    element('more').hidden = !nextBefore;
  }
  async function loadFiles(more = false) {
    if (!more) { invalidate(); selectedFile = null; files = []; nextBefore = null; clearPlayback(); renderFiles(); }
    if (!element('participant').value || !element('task').value) { element('file-count').textContent = 'Files appear here after you choose a participant and problem.'; status('Choose a participant and problem.'); return; }
    const ticket = generation, params = query(); if (more && nextBefore) params.set('beforeSubmission', nextBefore);
    status(more ? 'Loading older submitted files…' : 'Loading submitted files…'); element('load').disabled = true; element('more').disabled = true;
    try {
      const value = await request('files', params); if (ticket !== generation) return;
      const combined = more ? files.concat(value.files || []) : value.files || [];
      files = [...new Map(combined.map(file => [String(file.fileId), file])).values()]; nextBefore = value.nextBeforeSubmission || null; renderFiles();
      status(files.length ? 'Choose a submitted file.' + (value.notice ? ' ' + value.notice : '') : 'No submitted files were found for this participant and problem.');
    } catch (error) { if (ticket === generation && error.name !== 'AbortError') status(error.message); }
    finally { if (ticket === generation) { element('load').disabled = false; element('more').disabled = false; } }
  }
  async function chooseFile(file) {
    invalidate(); selectedFile = file; clearPlayback(); renderFiles();
    if (!file.hasHistory) { status(file.reason || 'No retained editing history is linked to this submitted file.'); element('empty').textContent = file.reason || 'No linked editing history is available. The official submission remains available through its submission link.'; return; }
    const ticket = generation, params = query(); params.set('intervalSeconds', element('interval').value);
    status('Preparing this file’s writing timeline…');
    try {
      const value = await request('files/' + encodeURIComponent(file.fileId) + '/timeline', params); if (ticket !== generation) return;
      timeline = value;
      element('filename').textContent = file.sourceFilename || file.filename;
      element('submission').textContent = 'Submission #' + file.submissionId + ' · ' + timestamp(file.submittedAt) + (file.language ? ' · ' + file.language : '');
      const correlation = value.correlation || {}, badge = element('correlation');
      badge.textContent = correlation.state === 'matched' ? 'Submitted bytes matched' : correlation.state === 'mismatch' ? 'Submitted bytes differ' : 'Submission match unavailable';
      badge.className = 'history-badge' + (correlation.state === 'matched' ? ' is-matched' : correlation.state === 'mismatch' ? ' is-mismatch' : ''); badge.title = correlation.detail || '';
      const summary = value.summary || {};
      element('summary').textContent = number(summary.editCount) + ' code edits · +' + number(summary.inserted) + ' / −' + number(summary.deleted) + ' characters · ' + number(summary.keyboardInputs) + ' key-linked edits · ' + number(summary.periodCount || value.periods?.length) + ' editing sessions';
      const thresholdLabels = Object.entries(value.thresholds || {}).filter(([, amount]) => ['string','number'].includes(typeof amount)).map(([name, amount]) => name.replace(/([A-Z])/g, ' $1').replaceAll('_',' ') + ': ' + amount);
      element('thresholds').textContent = thresholdLabels.join(' · ');
      element('player').hidden = false; element('empty').hidden = true; rebuildPoints(); renderMarkers(); notice(value.notices || []);
      if (!visiblePoints.length) { status('No retained editing periods are available for this submitted file.'); clearSource(); updateButtons(); return; }
      status('Review this submitted file’s code edits. Markers are cues for human review, not plagiarism findings.');
      await seek(visiblePoints.length - 1);
    } catch (error) { if (ticket === generation && error.name !== 'AbortError') { status(error.message); clearSource(); } }
  }
  async function seek(position, autoplay = false) {
    if (!autoplay) pause();
    if (!selectedFile || !visiblePoints.length) return false;
    position = Math.max(0, Math.min(visiblePoints.length - 1, position));
    const point = visiblePoints[position], file = selectedFile, ticket = generation, seekTicket = ++seekGeneration;
    abort(replayControllers); busy = true; index = position; markCurrent(); updateButtons(); clearSource();
    const pointPosition = (timeline?.points || []).findIndex(candidate => candidate.id === point.id), previous = pointPosition > 0 ? timeline.points[pointPosition - 1] : null;
    const paramsFor = item => { const params = query(); params.set('sessionId', item.sessionId); params.set('through', String(item.sequence)); return params; };
    element('event').textContent = pointLabel(point, position) + (describePoint(point) ? ' · ' + describePoint(point) : '') + ' · loading source…';
    try {
      const [value, before] = await Promise.all([
        request('files/' + encodeURIComponent(file.fileId) + '/replay', paramsFor(point), true),
        element('compare').checked && previous ? request('files/' + encodeURIComponent(file.fileId) + '/replay', paramsFor(previous), true).catch(error => error.name === 'AbortError' ? Promise.reject(error) : {available:false, notices:[error.message]}) : null,
      ]);
      if (ticket !== generation || seekTicket !== seekGeneration) return false;
      const available = value.available && typeof value.content === 'string';
      element('source').value = available ? value.content : '';
      element('event').textContent = pointLabel(point, position) + (describePoint(point) ? ' · ' + describePoint(point) : '') + (available ? ' · read-only source' : ' · source unavailable at this position');
      element('source-title').textContent = point.kind === 'submission' ? 'Source at submission' : 'Source at this period';
      element('after-label').textContent = point.kind === 'initial' ? 'Starting snapshot' : point.kind === 'submission' ? 'Submitted version' : 'After this editing period';
      element('before').value = before?.available && typeof before.content === 'string' ? before.content : '';
      element('before-status').textContent = !element('compare').checked ? '' : !previous ? 'This is the first retained snapshot.' : before?.available && typeof before.content === 'string' ? '' : 'The file is unavailable at the previous recorded position.';
      notice([...(timeline?.notices || []), ...(value.notices || []), ...(before?.notices || [])], !available && point.kind !== 'initial');
      const emptyStart = point.kind === 'initial' && value.content === null;
      if (!available && !emptyStart) pause();
      return available || emptyStart;
    } catch (error) { if (ticket === generation && seekTicket === seekGeneration && error.name !== 'AbortError') { pause(); clearSource(); status(error.message); } return false; }
    finally { if (ticket === generation && seekTicket === seekGeneration) { busy = false; updateButtons(); } }
  }
  function schedule(token = playbackGeneration) {
    clearTimeout(timer); timer = null;
    if (!playing || token !== playbackGeneration) return;
    if (index >= visiblePoints.length - 1) { pause(); return; }
    if (busy) { timer = setTimeout(() => { timer = null; schedule(token); }, 80); return; }
    const current = visiblePoints[index], next = visiblePoints[index + 1], speed = Number(element('speed').value) || 1;
    const gap = current?.sessionId === next.sessionId ? Math.max(0, Number(next.offsetMs) - Number(current.offsetMs)) : 1000;
    const delay = element('skip-idle').checked ? 450 / speed : Math.min(15000, Math.max(150, gap / speed));
    timer = setTimeout(async () => {
      timer = null;
      if (!playing || token !== playbackGeneration) return;
      const advanced = await seek(index + 1, true);
      if (playing && token === playbackGeneration && advanced) schedule(token);
    }, delay);
  }
  for (const id of ['participant','task']) element(id).addEventListener('change', () => void loadFiles());
  element('load').addEventListener('click', () => void loadFiles()); element('more').addEventListener('click', () => void loadFiles(true));
  element('interval').addEventListener('change', () => { if (selectedFile) void chooseFile(selectedFile); });
  element('timeline').addEventListener('input', () => void seek(Number(element('timeline').value)));
  element('previous').addEventListener('click', () => void seek(index - 1)); element('next').addEventListener('click', () => void seek(index + 1));
  element('marked-only').addEventListener('change', () => { pause(); const preferred = visiblePoints[index]?.id; rebuildPoints(preferred); if (visiblePoints.length) void seek(index); else clearSource(); });
  element('compare').addEventListener('change', () => { element('before-panel').hidden = !element('compare').checked; element('source-grid').classList.toggle('is-comparing', element('compare').checked); if (index >= 0) void seek(index); });
  element('more-markers').addEventListener('click', () => { markerLimit += 100; renderMarkers(); });
  element('play').addEventListener('click', async () => {
    if (playing) { pause(); return; }
    if (!visiblePoints.length) return;
    const token = ++playbackGeneration; playing = true; element('play').textContent = 'Pause';
    if (index >= visiblePoints.length - 1 || index < 0) { if (!await seek(0, true)) { if (token === playbackGeneration) pause(); return; } }
    if (playing && token === playbackGeneration) schedule(token);
  });
  for (const id of ['speed','skip-idle']) element(id).addEventListener('change', () => { if (playing) { playbackGeneration++; schedule(playbackGeneration); } });
  window.addEventListener('pagehide', () => { invalidate(); clearSource(); });
})();
