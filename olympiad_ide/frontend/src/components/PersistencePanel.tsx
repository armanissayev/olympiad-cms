import { DiffEditor } from '@monaco-editor/react'
import { Cloud, CloudOff, Download, History, RotateCw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { persistence } from '../persistence/controller'
import { usePersistenceStatus } from '../persistence/status'
import { useWorkspaceStore } from '../store/workspaceStore'
import { monacoThemeName } from '../editor/monaco'
import { toDocument, type RecoverySnapshot } from '../persistence/types'

export function SyncIndicator() {
  const status = usePersistenceStatus((s) => s.status)
  const online = usePersistenceStatus((s) => s.online)
  return <button className="sync-indicator" aria-label={`Synchronization: ${status}`} onClick={() => usePersistenceStatus.setState({ detailsOpen: true })}>
    {online ? <Cloud className="h-3.5 w-3.5" /> : <CloudOff className="h-3.5 w-3.5" />}
    {status}
  </button>
}

function exportRecovery() {
  let legacy: string | null = null
  try { legacy = localStorage.getItem('olympiad-ide-phase1') } catch { /* Export in-memory work even when browser storage is blocked. */ }
  const archive = { exportedAt: new Date().toISOString(), workspace: useWorkspaceStore.getState().workspace,
    document: toDocument(useWorkspaceStore.getState()), conflict: usePersistenceStatus.getState().conflict,
    legacy }
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([JSON.stringify(archive, null, 2)], { type: 'application/json' }))
  link.download = `olympiad-recovery-${Date.now()}.json`
  link.click()
  URL.revokeObjectURL(link.href)
}

export function PersistencePanel() {
  const state = usePersistenceStatus()
  const theme = useWorkspaceStore((s) => s.settings.theme)
  const [message, setMessage] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState('')
  const [snapshots, setSnapshots] = useState<RecoverySnapshot[]>([])
  const [archives, setArchives] = useState<{ key: string; value: string }[]>([])
  const [storageWarning, setStorageWarning] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showConflict, setShowConflict] = useState(false)

  const action = async (run: () => Promise<unknown>) => {
    setBusy(true)
    setMessage(null)
    try { await run() } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }

  useEffect(() => {
    if (!state.detailsOpen) return
    void persistence.repository.db.recoverySnapshots.where('workspaceId')
      .equals(useWorkspaceStore.getState().workspace.id).reverse().sortBy('createdAt')
      .then(setSnapshots).catch(() => setMessage('Recovery storage is unavailable. Export your current work.'))
    void persistence.repository.db.metadata.where('key').startsWith(`resolved:${useWorkspaceStore.getState().workspace.id}:`)
      .toArray().then(setArchives).catch(() => undefined)
    void navigator.storage?.estimate().then((estimate) => {
      if (estimate.quota && (estimate.usage ?? 0) / estimate.quota > 0.85) setStorageWarning('Browser storage is over 85% full. Export a backup and free space.')
    }).catch(() => undefined)
  }, [state.detailsOpen])

  const conflict = state.conflict
  const fileIds = conflict ? Array.from(new Set([...Object.keys(conflict.local.nodes), ...Object.keys(conflict.server.document.nodes)])) : []
  const changed = fileIds.filter((id) => JSON.stringify(conflict?.local.nodes[id]) !== JSON.stringify(conflict?.server.document.nodes[id]))
  const fileId = changed.includes(selectedFile) ? selectedFile : changed[0]
  const localNode = fileId ? conflict?.local.nodes[fileId] : undefined
  const serverNode = fileId ? conflict?.server.document.nodes[fileId] : undefined

  return <>
    {(state.error || conflict) && <div className="persistence-alert" role="alert">
      <span>{state.error ? `Save Error: ${state.error}` : 'Conflict: both versions are preserved. Review before synchronizing.'}</span>
      <button onClick={() => { usePersistenceStatus.setState({ detailsOpen: true }); setShowConflict(!!conflict) }}>Review</button>
      <button onClick={exportRecovery}>Export work</button>
    </div>}
    {state.detailsOpen && <div className="sync-popover" role="dialog" aria-label="Synchronization details">
      <div className="flex items-center justify-between border-b border-[var(--border)] pb-2">
        <strong>{state.status}</strong>
        <button className="tiny-icon-button" aria-label="Close synchronization details" onClick={() => usePersistenceStatus.setState({ detailsOpen: false })}><X size={15} /></button>
      </div>
      <p>{state.localPending ? `${state.localPending} local writes still committing` : state.error ? 'Some changes may not be committed locally.' : 'IndexedDB has committed your current local changes.'}</p>
      <p>Pending operations: {state.pendingOperations}</p>
      <p>Last sync: {state.lastSyncedAt ? new Date(state.lastSyncedAt).toLocaleString() : 'No server acknowledgement yet'}</p>
      <p>Connection: {state.online ? 'Backend reachable' : 'Backend unreachable; editing continues locally'}</p>
      {state.error && <p className="text-[#f48771]">{state.error}</p>}
      {message && <p role="alert" className="text-[#f48771]">{message}</p>}
      {storageWarning && <p role="alert" className="text-[#f48771]">{storageWarning}</p>}
      <div className="flex flex-wrap gap-2 py-2">
        <button className="tool-button primary" disabled={busy} onClick={() => void action(() => persistence.retry())}><RotateCw size={13} /> Retry</button>
        <button className="tool-button" disabled={busy} onClick={() => void action(() => persistence.checkpoint())}>Save checkpoint</button>
        <button className="tool-button" onClick={exportRecovery}><Download size={13} /> Export current work</button>
        {conflict && <button className="tool-button primary" onClick={() => setShowConflict(true)}>Resolve conflict</button>}
      </div>
      {archives.length > 0 && <div className="mt-3 border-t border-[var(--border)] pt-3">
        <strong>Preserved conflict branches</strong>
        <p className="text-[var(--muted)]">Restore an earlier local branch into its own recovered folder.</p>
        {archives.map((archive) => <div className="snapshot-row" key={archive.key}>
          <span>{new Date((JSON.parse(archive.value) as { createdAt: string }).createdAt).toLocaleString()}</span>
          <button className="tool-button" disabled={busy} onClick={() => void action(() => persistence.restoreArchive(archive.key))}>Recover copy</button>
        </div>)}
      </div>}
      <div className="border-t border-[var(--border)] pt-3">
        <div className="flex items-center gap-2"><History size={14} /><strong>Recovery snapshots</strong></div>
        <p className="text-[var(--muted)]">Initial, periodic, and pre-delete copies. Restoring a snapshot creates a new edit.</p>
        <div className="max-h-44 overflow-auto">
          {snapshots.length === 0 ? <p>No local snapshots yet.</p> : snapshots.map((snapshot) => <div className="snapshot-row" key={snapshot.snapshotId}>
            <span>{snapshot.name}<small>{new Date(snapshot.createdAt).toLocaleString()} · {snapshot.reason}</small></span>
            <button className="tool-button" disabled={busy} onClick={() => void action(() => persistence.restoreSnapshot(snapshot.snapshotId))}>Restore</button>
          </div>)}
        </div>
      </div>
    </div>}
    {showConflict && conflict && <div className="conflict-overlay">
      <section className="conflict-dialog" role="dialog" aria-modal="true" aria-label="Resolve workspace conflict">
        <header className="flex items-center justify-between border-b border-[var(--border)] p-3">
          <strong>Resolve workspace conflict</strong>
          <button className="tiny-icon-button" aria-label="Close conflict comparison" onClick={() => setShowConflict(false)}><X size={16} /></button>
        </header>
        <p className="px-3 text-xs">Left: your local work. Right: {conflict.kind === 'local' ? 'the other browser tab’s committed work' : `server revision ${conflict.server.revision}`}.</p>
        <p className="px-3 text-xs text-[var(--muted)]">Resolution covers the complete workspace, including file names, folders, deletions, and settings. Both versions remain in the recovery archive.</p>
        <div className="flex gap-2 px-3 py-2">
          <select aria-label="Conflict file" className="conflict-select" value={fileId ?? ''} onChange={(e) => setSelectedFile(e.target.value)}>
            {changed.map((id) => <option value={id} key={id}>{conflict.local.nodes[id]?.name ?? conflict.server.document.nodes[id]?.name}</option>)}
          </select>
          <span className="text-xs">Local: {localNode ? `${localNode.name} → ${localNode.parentId ?? '/'}` : 'deleted'} · Other: {serverNode ? `${serverNode.name} → ${serverNode.parentId ?? '/'}` : 'deleted'}</span>
        </div>
        <div className="min-h-0 flex-1">
          <DiffEditor original={localNode?.type === 'file' ? localNode.content : JSON.stringify(conflict.local.settings, null, 2)}
            modified={serverNode?.type === 'file' ? serverNode.content : JSON.stringify(conflict.server.document.settings, null, 2)}
            language={localNode?.type === 'file' ? localNode.language : 'plaintext'} theme={monacoThemeName(theme)}
            options={{ readOnly: true, originalEditable: false, automaticLayout: true, renderSideBySide: true, minimap: { enabled: false } }} />
        </div>
        {message && <p role="alert" className="px-3 text-xs text-[#f48771]">{message}</p>}
        <footer className="flex flex-wrap gap-2 border-t border-[var(--border)] p-3">
          <button className="tool-button primary" disabled={busy} onClick={() => void action(() => persistence.resolve('local'))}>Keep local version</button>
          <button className="tool-button" disabled={busy} onClick={() => void action(() => persistence.resolve('server'))}>Keep server version</button>
          <button className="tool-button" disabled={busy} onClick={() => void action(() => persistence.resolve('copy'))}>Save local as recovered copy</button>
          <button className="tool-button" onClick={exportRecovery}>Export both versions</button>
        </footer>
      </section>
    </div>}
  </>
}
