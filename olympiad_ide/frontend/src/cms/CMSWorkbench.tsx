import { useEffect, useRef, useState } from 'react'
import { database } from '../persistence/database'
import { useWorkspaceStore, getNodePath } from '../store/workspaceStore'
import { cmsEnabled, checkCMSContext, currentTask, safeCMSLink, useCMSSession } from './session'
import { captureOfficial, getFeedback, listHistory, persistIntent, reconcileIntent, sendIntent } from './submissions'
import { switchTaskWorkspace } from './taskWorkspace'
import { participantMessage, sourceLanguage } from './submissionPresentation'
import type { OfficialHistory, ParticipantStatus, StoredIntent } from './types'
import './cms.css'

const phases: Record<number, string> = { '-2': 'Not started', '-1': 'Start your participation in CMS', 0: 'Contest active', 1: 'Your contest time ended', 2: 'Waiting for analysis', 3: 'Practice submissions', 4: 'Contest ended' }
const unresolved = (intent: StoredIntent) => ['unknown', 'pending', 'confirmed'].includes(intent.state)
export function CMSWorkbench() {
  const session = useCMSSession(), task = currentTask(), nodes = useWorkspaceStore(state => state.nodes)
  const workspaceId = useWorkspaceStore(state => state.workspace.id)
  const [open, setOpen] = useState(false), [mapping, setMapping] = useState<Record<string, string>>({}), [chosenLanguage, setChosenLanguage] = useState('')
  const [intents, setIntents] = useState<StoredIntent[]>([]), [history, setHistory] = useState<OfficialHistory[]>([])
  const [feedback, setFeedback] = useState<ParticipantStatus | null>(null), [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null), [busy, setBusy] = useState(false), [tick, setTick] = useState(Date.now())
  const working = useRef(false)
  const refreshLocal = async () => {
    const id = useCMSSession.getState().taskId
    if (id !== null) setIntents(await database.officialSubmissionIntents.where('taskId').equals(id).reverse().sortBy('createdAt'))
  }
  useEffect(() => {
    if (!cmsEnabled) return
    const clock = setInterval(() => setTick(Date.now()), 1000), auth = setInterval(() => { void checkCMSContext() }, 30_000)
    return () => { clearInterval(clock); clearInterval(auth) }
  }, [])
  useEffect(() => {
    setMapping({}); setChosenLanguage(''); setIntents([]); setHistory([]); setFeedback(null); setSelected(null); setNotice(null); setError(null)
  }, [workspaceId, session.taskId])
  useEffect(() => {
    if (!open || session.taskId === null || session.switching) return
    const taskId = session.taskId, store = database
    let disposed = false, timer: ReturnType<typeof setTimeout>
    const refresh = async () => {
      try {
        const local = await store.officialSubmissionIntents.where('taskId').equals(taskId).reverse().sortBy('createdAt')
        if (!disposed) setIntents(local)
        if (!useCMSSession.getState().paused) {
          for (const intent of local.filter(unresolved).slice(0, 10)) {
            if (disposed || useCMSSession.getState().switching) break
            await reconcileIntent(intent)
          }
          if (disposed || useCMSSession.getState().switching) return
          const response = await listHistory(taskId)
          if (!disposed) { setHistory(response.submissions); setError(null) }
          if (selected) { const status = await getFeedback(taskId, selected); if (!disposed) setFeedback(status) }
        }
      } catch (failure) { if (!disposed) setError(participantMessage(failure)) }
      if (!disposed) timer = setTimeout(() => void refresh(), 5000)
    }
    void refresh()
    return () => { disposed = true; clearTimeout(timer) }
  }, [open, session.taskId, session.switching, selected])
  if (!cmsEnabled || !session.context) return null
  const context = session.context, blocked = busy || session.switching
  const left = context.phaseEnd ? Math.max(0, Math.ceil((Date.parse(context.phaseEnd) - Date.parse(context.serverTime) - (tick - session.receivedAt)) / 1000)) : null
  const remaining = left === null ? null : `${Math.floor(left / 3600)}:${String(Math.floor(left / 60) % 60).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`
  const files = Object.values(nodes).filter(node => node.type === 'file')
  const source = task?.submissionFormat[0] ? nodes[mapping[task.submissionFormat[0]] ?? ''] : undefined
  const language = chosenLanguage || (task && source?.type === 'file' ? sourceLanguage(task, source.name, context.executionProfileMap) : '')
  const canSubmit = !!task?.supported && !session.paused && !!language && task.submissionFormat.every(filename => nodes[mapping[filename] ?? '']?.type === 'file')
  const perform = async (operation: () => Promise<void>) => {
    if (working.current) return
    working.current = true; setBusy(true); setError(null)
    try { await operation() } catch (failure) { setError(participantMessage(failure)) }
    finally { working.current = false; setBusy(false) }
  }
  const switchTask = (id: number) => perform(async () => { await switchTaskWorkspace(id) })
  const openSubmit = () => {
    const state = useWorkspaceStore.getState(), file = state.groups[state.activeGroupId].activeFileId
    setMapping(task?.submissionFormat.length === 1 && file ? { [task.submissionFormat[0]!]: file } : {})
    setChosenLanguage(''); setError(null); setNotice(null); setOpen(true)
  }
  const submit = () => perform(async () => {
    if (!task || !canSubmit) return
    const captured = await captureOfficial(task, language, mapping)
    const local = await database.officialSubmissionIntents.where('taskId').equals(task.id).toArray()
    if (local.some(unresolved)) { setIntents(local); setNotice('Check the pending submission below before submitting again.'); return }
    await persistIntent(captured)
    const result = await sendIntent(captured.intentId)
    await refreshLocal()
    if (result.state === 'admitted') {
      setNotice(result.receipt?.official === false ? 'Practice submission received.' : 'Submission received. Waiting for judging…')
      setSelected(result.receipt!.submissionId)
      const response = await listHistory(task.id); setHistory(response.submissions)
    } else if (result.state === 'rejected') setError('CMS could not accept this submission. Check the selected problem and file.')
    else setNotice('Checking whether CMS received your submission. Your submitted file is saved.')
  })
  return <div className="cms-chrome">
    <div className="cms-bar">
      <strong>{context.contest.description || context.contest.name}</strong><span>{context.user.username}</span>
      <span>{phases[context.actualPhase] ?? 'CMS phase'}{remaining ? ` · ${remaining}` : ''}</span>
      <label className="cms-problem-picker"><span className="sr-only">Problem</span><select aria-label="Contest task" value={session.taskId ?? ''} disabled={blocked || session.paused} onChange={event => void switchTask(Number(event.target.value))}>
        {!context.tasks.length && <option value="">Problems unavailable</option>}{context.tasks.map(item => <option value={item.id} key={item.id}>{item.name} — {item.title}</option>)}
      </select></label>
      <a href={safeCMSLink(context.links.fallback)}>CMS participant page</a>
      <div className="cms-submit-region"><button className="cms-submit-launch" disabled={blocked} onClick={openSubmit}>Submit</button></div>
    </div>
    {session.paused && <div className="cms-auth-notice" role="status">{session.message} <button onClick={() => void checkCMSContext()}>Check sign-in</button> <a href={safeCMSLink(context.links.login)}>CMS login</a></div>}
    {open && <aside className="cms-panel cms-submit-panel" role="dialog" aria-label="Submit solution" onKeyDown={event => { if (event.key === 'Escape' && !blocked) setOpen(false) }}>
      <div className="cms-panel-heading"><h2>Submit solution</h2><button onClick={() => setOpen(false)} disabled={blocked} aria-label="Close submit dialog">×</button></div>
      <form onSubmit={event => { event.preventDefault(); void submit() }}>
        <label>Problem<select aria-label="Submission problem" value={session.taskId ?? ''} disabled={blocked || session.paused} onChange={event => void switchTask(Number(event.target.value))}>{context.tasks.map(item => <option key={item.id} value={item.id}>{item.name} — {item.title}</option>)}</select></label>
        {task?.submissionFormat.map(filename => <label key={filename}>{task.submissionFormat.length === 1 ? 'File' : filename}<select aria-label={task.submissionFormat.length === 1 ? 'Submission file' : `Submission file for ${filename}`} value={mapping[filename] ?? ''} disabled={blocked} onChange={event => { setMapping({ ...mapping, [filename]: event.target.value }); setChosenLanguage(''); setNotice(null) }}><option value="">Choose a source file</option>{files.map(file => <option key={file.id} value={file.id}>{getNodePath(nodes, file.id)}</option>)}</select></label>)}
        {!language && source && task && <label>Language<select aria-label="Submission language" value={chosenLanguage} disabled={blocked} onChange={event => setChosenLanguage(event.target.value)}><option value="">Choose a language</option>{task.languages.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
        {language && task && <p className="cms-submission-language">{task.languages.find(item => item.id === language)?.name}</p>}
        {!task?.supported && <p role="status">Submit this problem through <a href={safeCMSLink(task?.submissionsUrl ?? context.links.fallback)}>CMS</a>.</p>}
        <button className="cms-submit-action" type="submit" disabled={!canSubmit || blocked}>{busy && !session.switching ? 'Please wait…' : 'Submit solution'}</button>
      </form>
      {notice && <p role="status" className="cms-submission-notice">{notice}</p>}
      {error && <p className="cms-error" role="alert">{error}</p>}
      {intents.filter(unresolved).map(intent => <section className="cms-pending-submission" key={intent.intentId}><strong>Submission awaiting confirmation</strong><p>{new Date(intent.createdAt).toLocaleTimeString()}</p><button disabled={blocked || session.paused} onClick={() => void perform(async () => { await reconcileIntent(intent); await refreshLocal() })}>Check submission</button><button disabled={blocked || session.paused} onClick={() => void perform(async () => { const result = await sendIntent(intent.intentId); await refreshLocal(); if (result.state === 'admitted') setNotice('Submission received.') })}>Retry saved submission</button></section>)}
      {!!history.length && <section className="cms-recent-submissions"><h3>Recent submissions</h3>{history.slice(0, 5).map(item => <button className="cms-result-row" key={item.submissionId} disabled={blocked} onClick={() => { setSelected(item.submissionId); setFeedback(null) }}><span>{item.status.status_text}</span><small>{new Date(item.receivedAt).toLocaleTimeString()}</small>{item.status.public_score !== undefined && <span>{item.status.public_score} / {item.status.max_public_score}</span>}</button>)}</section>}
      {feedback && <section className="cms-feedback" aria-label="Submission result"><strong>{feedback.status_text}</strong>{feedback.public_score !== undefined && <p>Score: {feedback.public_score} / {feedback.max_public_score}</p>}{feedback.score !== undefined && <p>Score: {feedback.score} / {feedback.max_score}</p>}{feedback.compilation?.stderr && <details><summary>Compiler messages</summary><pre>{feedback.compilation.stderr}</pre></details>}</section>}
      {task && <a className="cms-all-submissions" href={safeCMSLink(task.submissionsUrl)}>All submissions in CMS</a>}
    </aside>}
  </div>
}
