import { useEffect, useState } from 'react'
import { database } from '../persistence/database'
import { persistence } from '../persistence/controller'
import { telemetry } from '../telemetry/collector'
import { telemetrySync } from '../telemetry/telemetrySync'
import { executions } from '../execution/controller'
import { executionResources } from '../execution/resources'
import { getNodePath, useWorkspaceStore } from '../store/workspaceStore'
import { cmsEnabled, checkCMSContext, currentTask, safeCMSLink, selectTask, useCMSSession } from './session'
import { captureOfficial, getFeedback, listHistory, persistIntent, reconcileIntent, sendIntent } from './submissions'
import { applyImport, exportWorkspace, planImport, type ImportPlan } from './transfer'
import type { OfficialHistory, ParticipantStatus, StoredIntent } from './types'
import './cms.css'

const phases: Record<number, string> = { '-2': 'Not started', '-1': 'Start your participation in CMS', 0: 'Contest active', 1: 'Your contest time ended', 2: 'Waiting for analysis', 3: 'Analysis — unofficial submissions', 4: 'Contest ended' }
export function CMSWorkbench() {
  const session = useCMSSession(), task = currentTask(), nodes = useWorkspaceStore(s => s.nodes)
  const [open, setOpen] = useState(false), [language, setLanguage] = useState(''), [mapping, setMapping] = useState<Record<string, string>>({})
  const [draft, setDraft] = useState<StoredIntent | null>(null), [intents, setIntents] = useState<StoredIntent[]>([]), [history, setHistory] = useState<OfficialHistory[]>([])
  const [historyOffset, setHistoryOffset] = useState(0), [nextOffset, setNextOffset] = useState<number | null>(null)
  const [feedback, setFeedback] = useState<ParticipantStatus | null>(null), [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null), [busy, setBusy] = useState(false), [tick, setTick] = useState(Date.now()), [importPlan, setImportPlan] = useState<ImportPlan | null>(null)
  const message = (e: unknown) => setError(e instanceof Error ? e.message : String(e))
  const refreshLocal = async () => { if (session.taskId !== null) setIntents(await database.officialSubmissionIntents.where('taskId').equals(session.taskId).reverse().sortBy('createdAt')) }
  useEffect(() => {
    if (!cmsEnabled) return
    const clock = setInterval(() => setTick(Date.now()), 1000)
    const auth = setInterval(() => { void checkCMSContext() }, 30_000)
    return () => { clearInterval(clock); clearInterval(auth) }
  }, [])
  useEffect(() => {
    if (!open || session.taskId === null) return
    const taskId = session.taskId
    let disposed = false, timer: ReturnType<typeof setTimeout>
    let attempts = 0
    const refresh = async () => {
      try {
        let local = await database.officialSubmissionIntents.where('taskId').equals(taskId).reverse().sortBy('createdAt')
        if (!disposed) setIntents(local)
        if (!useCMSSession.getState().paused) {
          // Reload reconciliation only retrieves receipts; it never invents another submit action.
          for (const intent of local.filter(item => item.state === 'unknown' || item.state === 'pending').slice(0, 10)) await reconcileIntent(intent)
          local = await database.officialSubmissionIntents.where('taskId').equals(taskId).reverse().sortBy('createdAt')
        }
        if (!disposed) setIntents(local)
        if (!useCMSSession.getState().paused && task) {
          const response = await listHistory(task.id, historyOffset)
          if (!disposed) { setHistory(response.submissions); setNextOffset(response.nextOffset) }
          if (selected) { const status = await getFeedback(task.id, selected); if (!disposed) setFeedback(status) }
          attempts = 0
        }
      } catch (e) { attempts++; if (!disposed) message(e) }
      if (!disposed) timer = setTimeout(() => void refresh(), Math.min(60_000, 10_000 * 2 ** attempts) * (0.85 + Math.random() * 0.3))
    }
    void refresh()
    return () => { disposed = true; clearTimeout(timer) }
  }, [open, task, selected, session.taskId, historyOffset])
  if (!cmsEnabled || !session.context) return null
  const context = session.context
  const left = context.phaseEnd ? Math.max(0, Math.ceil((Date.parse(context.phaseEnd) - Date.parse(context.serverTime) - (tick - session.receivedAt)) / 1000)) : null
  const remaining = left === null ? null : `${Math.floor(left / 3600)}:${String(Math.floor(left / 60) % 60).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`
  const canSubmit = !!task?.supported && !session.paused
  const perform = async (operation: () => Promise<void>) => { setBusy(true); setError(null); try { await operation() } catch (e) { message(e) } finally { setBusy(false) } }
  const switchTask = (id: number) => perform(async () => {
    await persistence.flush(); await executionResources.flush(); await telemetry.complete('task-switch')
    telemetrySync.stop(); persistence.stop(); executions.stop(); telemetry.stop()
    selectTask(id); location.reload()
  })
  return <div className="cms-chrome">
    <div className="cms-bar">
      <strong>{context.contest.description || context.contest.name}</strong><span>{context.user.username}</span>
      <span title="Server-derived participant phase; countdown is advisory">{phases[context.actualPhase] ?? 'CMS phase'}{remaining ? ` · ${remaining}` : ''}</span>
      <select aria-label="Contest task" value={session.taskId ?? ''} disabled={busy || session.paused} onChange={e => void switchTask(Number(e.target.value))}>
        {!context.tasks.length && <option value="">Tasks unavailable in this phase</option>}
        {context.tasks.map(item => <option value={item.id} key={item.id}>{item.name} — {item.title}</option>)}
      </select>
      <button className="tool-button" onClick={() => setOpen(!open)}>Submit &amp; official feedback</button>
      <a href={safeCMSLink(context.links.fallback)} target="_blank" rel="noreferrer">CMS participant page</a>
    </div>
    {session.paused && <div className="cms-auth-notice" role="status">{session.message} <button onClick={() => void checkCMSContext()}>Check authentication</button> <a href={safeCMSLink(context.links.login)} target="_blank" rel="noreferrer">CMS login</a> <button onClick={() => void perform(async () => { await persistence.flush(); await executionResources.flush(); await telemetry.flush(); location.reload() })}>Reopen for current account</button></div>}
    {open && <aside className="cms-panel" aria-label="Official CMS submissions">
      <div className="cms-panel-heading"><h2>Official CMS submissions</h2><button onClick={() => setOpen(false)} aria-label="Close CMS panel">×</button></div>
      <p>Custom Run tests use the IDE worker. Submit sends the reviewed source to CMS for official judging. Stop affects custom Run only.</p>
      <nav className="cms-links"><a href={safeCMSLink(context.links.announcements)} target="_blank" rel="noreferrer">Announcements</a><a href={safeCMSLink(context.links.clarifications)} target="_blank" rel="noreferrer">Clarifications</a><form action={safeCMSLink(context.links.logout)} method="post" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; void perform(async () => { await persistence.flush(); await executionResources.flush(); await telemetry.flush(); form.submit() }) }}><input type="hidden" name="_xsrf" value={context.csrfToken} /><button type="submit" disabled={busy}>CMS logout</button></form></nav>
      {task && <>
        <h3>{task.name} — {task.title}</h3>
        <nav className="cms-links"><a href={safeCMSLink(task.statementUrl)} target="_blank" rel="noreferrer">Task in CMS</a>{task.statements.map(item => <a key={item.language} href={safeCMSLink(item.url)} target="_blank" rel="noreferrer">Statement {item.language}</a>)}{task.attachments.map(item => <a key={item.name} href={safeCMSLink(item.url)} target="_blank" rel="noreferrer">{item.name}</a>)}</nav>
        {!task.supported && <p role="status">{task.reason || 'This task requires the standard CMS submission workflow.'} <a href={safeCMSLink(task.submissionsUrl)} target="_blank" rel="noreferrer">Open CMS submissions</a></p>}
        <label>CMS language<select aria-label="CMS submission language" value={language} onChange={e => { setLanguage(e.target.value); setDraft(null) }} disabled={busy}><option value="">Choose the CMS toolchain</option>{task.languages.map(item => <option key={item.id} value={item.id}>{item.name} ({item.id})</option>)}</select></label>
        {task.customRunSupported === false && <p role="status">Custom Run is unavailable: {task.customRunReason || 'This task requires a CMS-specific execution harness.'}</p>}
        <p className="cms-note">Custom C++17/C++20/Python/Java profiles do not select the official CMS compiler. Only the CMS languages above are permitted.</p>
        {context.executionProfileMap && <details><summary>Custom and CMS toolchain mapping</summary>{Object.entries(context.executionProfileMap).map(([profile, entry]) => <p key={profile}>{profile} → {entry.enabled ? entry.cmsLanguage : 'Unavailable for official submission'}; versions: {entry.versionVerification}. {entry.reason}</p>)}</details>}
        {task.submissionFormat.map(filename => <label key={filename}>{filename}<select aria-label={`Source file for ${filename}`} value={mapping[filename] ?? ''} disabled={busy} onChange={e => { setMapping({ ...mapping, [filename]: e.target.value }); setDraft(null) }}><option value="">Select one source file</option>{Object.values(nodes).filter(node => node.type === 'file').map(node => <option key={node.id} value={node.id}>{getNodePath(nodes, node.id)}</option>)}</select></label>)}
        <button disabled={!canSubmit || busy || !language} onClick={() => void perform(async () => setDraft(await captureOfficial(task, language, mapping)))}>Capture source for review</button>
        {draft && <section className="cms-confirm" aria-label="Confirm immutable submission"><h3>Review captured source</h3><p>Task {task.name} · CMS language {draft.body.language}. Later edits do not change this snapshot. {context.actualPhase === 3 ? 'This is an unofficial analysis submission.' : ''}</p>
          <p>Recording comparison: {draft.correlation?.state ?? 'unknown'}. {draft.correlation?.reason}</p>
          {draft.body.files.map(file => <details key={file.filename} open><summary>{file.sourceFilename} → {file.filename}</summary><code className="cms-hash">SHA-256 {draft.hashes[file.filename]}</code><pre>{file.content}</pre></details>)}
          <button disabled={!canSubmit || busy} onClick={() => void perform(async () => { await persistIntent(draft); const result = await sendIntent(draft.intentId); setDraft(null); await refreshLocal(); if (result.error) setError(result.error) })}>Confirm and submit captured source</button><button disabled={busy} onClick={() => setDraft(null)}>Discard capture</button>
        </section>}
        <h3>CMS history and feedback</h3><p>Feedback is refreshed while this panel is open, including completed results after rejudging. Tokens, task-specific details and source downloads remain available in CMS.</p>
        {history.map(item => <div className="cms-history" key={item.submissionId}><button onClick={() => { setFeedback(null); setSelected(item.submissionId) }}>#{item.submissionId} · {item.status.status_text}</button><small>{item.receivedAt} · {item.language} · {item.official ? 'official' : 'analysis / unofficial'}</small>{item.status.public_score !== undefined && <span>Public: {item.status.public_score} / {item.status.max_public_score}</span>}{item.status.score !== undefined && <span>Full: {item.status.score} / {item.status.max_score}</span>}<a href={safeCMSLink(item.cwsUrl)} target="_blank" rel="noreferrer">CMS details / tokens</a></div>)}
        <div><button disabled={historyOffset === 0} onClick={() => setHistoryOffset(Math.max(0, historyOffset - 30))}>Newer submissions</button><button disabled={nextOffset === null} onClick={() => { if (nextOffset !== null) setHistoryOffset(nextOffset) }}>Older submissions</button></div>
        {feedback && <div className="cms-history"><strong>{feedback.status_text}</strong>{feedback.public_score !== undefined && <p>Public score: {feedback.public_score} / {feedback.max_public_score}</p>}{feedback.score !== undefined && <p>Full score: {feedback.score} / {feedback.max_score}</p>}{feedback.task_public_score !== undefined && <p>Task public score: {feedback.task_public_score}{feedback.task_score_is_partial ? ' (partial)' : ''}</p>}{feedback.task_tokened_score !== undefined && <p>Task tokened score: {feedback.task_tokened_score}</p>}{feedback.detailsText && <pre>{feedback.detailsText}{feedback.detailsTruncated ? '\n[Details truncated by CMS]' : ''}</pre>}{feedback.compilation && <><p>{feedback.compilation.text}</p>{feedback.compilation.stdout && <pre>{feedback.compilation.stdout}{feedback.compilation.stdoutTruncated ? '\n[Compiler stdout truncated]' : ''}</pre>}{feedback.compilation.stderr && <pre>{feedback.compilation.stderr}{feedback.compilation.stderrTruncated ? '\n[Compiler stderr truncated]' : ''}</pre>}</>}</div>}
      </>}
        <h3>Submission intents on this device</h3>
        {!intents.length && <p>No confirmed submissions from this task workspace.</p>}
        {intents.map(intent => <div className="cms-history" key={intent.intentId}><strong>{intent.state === 'admitted' ? `CMS received ${intent.receipt?.submissionId}` : intent.state === 'unknown' ? 'Outcome unknown — resolve receipt before retry' : intent.state === 'pending' ? 'Pending — receipt unconfirmed' : intent.state === 'confirmed' ? 'Captured — not yet admitted' : 'Rejected by CMS'}</strong><small>{intent.receipt?.receivedAt ?? intent.createdAt}</small>{intent.correlation && <small>Recording comparison: {intent.correlation.state} — {intent.correlation.reason}</small>}{intent.error && <p>{intent.error}</p>}
          {(intent.state === 'unknown' || intent.state === 'pending' || intent.state === 'confirmed') && <><button disabled={busy || session.paused} onClick={() => void perform(async () => { const result = await sendIntent(intent.intentId); await refreshLocal(); if (result.error) setError(result.error) })}>Resolve / retry exact source</button><button disabled={busy || session.paused} onClick={() => void perform(async () => { await reconcileIntent(intent); await refreshLocal() })}>Check receipt only</button></>}
        </div>)}
      <h3>Move source between browser origins</h3><p>Export from the old IDE origin, then import here. Existing ownership, telemetry and server receipts stay in their original storage. Import copies selected archive source into this task; it does not claim legacy server ownership.</p>
      <button onClick={exportWorkspace}>Export workspace source</button><label>Inspect source import<input aria-label="Import workspace archive" type="file" accept="application/json,.json" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) void perform(async () => { if (file.size > 12_000_000) throw new Error('Archive exceeds 12 MB'); setImportPlan(await planImport(await file.text())) }) }} /></label>
      {importPlan && <div><p>Dry run: {importPlan.files} files, {importPlan.bytes} UTF-8 bytes, {importPlan.collisions} UUID collisions to remap. Other file UUIDs are retained. A new recovery folder will be added. {importPlan.alreadyImported ? 'This archive is already imported.' : ''}</p><button disabled={busy || importPlan.alreadyImported} onClick={() => void perform(async () => { await applyImport(importPlan); setImportPlan(null) })}>Import reviewed source copy</button></div>}
      {error && <p className="cms-error" role="alert">{error}</p>}
    </aside>}
  </div>
}
