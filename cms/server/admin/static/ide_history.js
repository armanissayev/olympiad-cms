/* Administrator-only, read-only playback of verified server recordings. */
(() => {
  'use strict';
  const root = document.getElementById('ide-history');
  if (!root) return;
  const element = id => document.getElementById('history-' + id);
  let sessions = [], nextBefore = null, frame = null, current = '', generation = 0, timer = null, fetching = false;
  const status = text => { element('status').textContent = text; };
  function pause() { clearTimeout(timer); timer = null; element('play').textContent = 'Play'; }
  function options(select, rows, label) { select.replaceChildren(...rows.map(row => { const option = document.createElement('option'); option.value = row.id; option.textContent = label(row); return option; })); }
  function query() { return new URLSearchParams({userId: element('participant').value, taskId: element('task').value}); }
  async function request(suffix, params) {
    const response = await fetch(root.dataset.api + '/' + suffix + '?' + params, {credentials:'same-origin', cache:'no-store', redirect:'error'});
    if (!response.ok) { const value = await response.json().catch(() => null); throw Error(value?.error?.message || 'History request failed (' + response.status + ')'); }
    return response.json();
  }
  function path(nodes, node) { const names = [node.name]; let parent = node.parentId, guard = 0; while (parent && nodes[parent] && guard++ < 100) { names.unshift(nodes[parent].name); parent = nodes[parent].parentId; } return names.join('/'); }
  function renderSource() { const node = frame?.nodes[element('file').value]; element('source').value = node?.type === 'file' ? node.content : ''; }
  function clearFrame() { frame=null; element('source').value=''; element('file').replaceChildren(); element('event').textContent=''; element('notices').textContent=''; }
  async function seek(sequence, playing = false) {
    if (!current || fetching) return;
    if (!playing) pause();
    const ticket = generation, id = current, params = query(); params.set('through', String(sequence)); fetching = true;
    try {
      const value = await request('sessions/' + id + '/replay', params);
      if (ticket !== generation || id !== current) return;
      const previous = element('file').value; frame = value;
      element('timeline').value = String(value.sequence);
      element('notices').textContent = value.notices.join('\n');
      const files = Object.values(value.nodes).filter(node => node.type === 'file');
      options(element('file'), files, node => path(value.nodes, node));
      const selected = files.some(node => node.id === previous) ? previous : value.activeFileId;
      if (selected) element('file').value = selected;
      renderSource();
      const event = value.event;
      element('event').textContent = 'Event ' + value.sequence + ' / ' + value.session.lastSequence + ' · ' + (event ? event.eventType.replaceAll('_',' ') + ' · ' + event.clientTimestamp : 'Initial snapshot · ' + value.session.startedAt) + ' · read-only · checkpoint ' + value.checkpointSequence;
      element('previous').disabled = value.sequence <= 0;
      element('next').disabled = value.sequence >= value.session.lastSequence;
      status('Uploaded recording: ' + value.session.status + ' · integrity: ' + value.session.integrity + ' · ' + value.session.gaps + ' reported gaps');
      if (!value.available) pause();
    } catch (error) { if (ticket === generation) { pause(); status(error.message); } }
    finally { if (ticket === generation) fetching = false; }
  }
  async function load(more = false) {
    pause(); generation++; current = ''; clearFrame(); fetching = false; element('player').hidden = true;
    if (!element('participant').value || !element('task').value) { status('Choose a participant and problem.'); return; }
    const ticket = generation, params = query(); if (more && nextBefore) params.set('before', nextBefore);
    status('Loading uploaded recordings…');
    try {
      const value = await request('sessions', params); if (ticket !== generation) return;
      sessions = more ? sessions.concat(value.sessions) : value.sessions; nextBefore = value.nextBefore;
      options(element('session'), [{id:''}, ...sessions], row => row.id ? row.startedAt + ' · ' + row.lastSequence + ' events · ' + row.integrity : 'Choose recording');
      element('more').hidden = !nextBefore; status(sessions.length ? value.notice : 'No uploaded recording is available for this participant/problem. Browser-only or expired events cannot be shown.');
    } catch (error) { if (ticket === generation) status(error.message); }
  }
  element('load').addEventListener('click', () => void load());
  element('more').addEventListener('click', () => void load(true));
  for (const id of ['participant','task']) element(id).addEventListener('change', () => { pause(); generation++; current = ''; clearFrame(); fetching = false; sessions=[]; nextBefore=null; element('player').hidden=true; element('more').hidden=true; options(element('session'), [{id:''}], () => 'Choose recording'); status('Choose Load recordings to view this selection.'); });
  element('session').addEventListener('change', () => { pause(); generation++; fetching=false; current=element('session').value; clearFrame(); const session=sessions.find(row=>row.id===current); element('player').hidden=!session; if(session){element('timeline').max=String(session.lastSequence);element('timeline').value='0';void seek(0);} });
  element('timeline').addEventListener('input', () => { pause(); if(fetching){generation++;fetching=false;} void seek(Number(element('timeline').value)); });
  element('previous').addEventListener('click', () => void seek(Math.max(0,Number(element('timeline').value)-1)));
  element('next').addEventListener('click', () => void seek(Number(element('timeline').value)+1));
  element('file').addEventListener('change', renderSource);
  async function advance() { if(!timer || !frame)return; const next=frame.sequence+1;if(next>frame.session.lastSequence){pause();return;} const before=frame.event?.monotonicOffsetMs||0;await seek(next,true);if(!timer || !frame)return;const after=frame.event?.monotonicOffsetMs||before;timer=setTimeout(advance,Math.min(5000,Math.max(25,(after-before)/Number(element('speed').value)))); }
  element('play').addEventListener('click', () => { if(timer){pause();return;} if(!frame)return;if(frame.sequence>=frame.session.lastSequence){void seek(0).then(()=>{element('play').textContent='Pause';timer=setTimeout(advance,25);});}else{element('play').textContent='Pause';timer=setTimeout(advance,25);} });
  window.addEventListener('pagehide', pause);
})();
