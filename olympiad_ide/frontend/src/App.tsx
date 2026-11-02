import { useEffect, useMemo, useState } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { ActivityBar } from './components/ActivityBar'
import { BottomPanel } from './components/BottomPanel'
import { QuickOpen } from './components/QuickOpen'
import { Sidebar } from './components/Sidebar'
import { StatusBar } from './components/StatusBar'
import { Toolbar } from './components/Toolbar'
import { EditorArea } from './components/editor/EditorArea'
import { defineOlympiadThemes, modelRegistry } from './editor/monaco'
import { useWorkspaceStore } from './store/workspaceStore'
import { PersistencePanel } from './components/PersistencePanel'
import { persistence } from './persistence/controller'
import { executions } from './execution/controller'
import { CMSWorkbench } from './cms/CMSWorkbench'
import { cmsEnabled, useCMSSession } from './cms/session'
import { debugging } from './debug/controller'

export default function App() {
  const workspaceId = useWorkspaceStore(state => state.workspace.id)
  const switchingTask = useCMSSession(state => state.switching)
  useEffect(() => { if (!switchingTask) void debugging.loadBreakpoints() }, [workspaceId, switchingTask])
  useEffect(() => {
    const stopDebugging = () => { void debugging.stop() }
    window.addEventListener('pagehide', stopDebugging)
    return () => window.removeEventListener('pagehide', stopDebugging)
  }, [])
  const theme = useWorkspaceStore((state) => state.settings.theme)
  const nodes = useWorkspaceStore((state) => state.nodes)
  const explorerVisible = useWorkspaceStore((state) => state.explorerVisible)
  const explorerSize = useWorkspaceStore((state) => state.explorerSize)
  const bottomPanelVisible = useWorkspaceStore((state) => state.bottomPanelVisible)
  const bottomPanelSize = useWorkspaceStore((state) => state.bottomPanelSize)
  const zenMode = useWorkspaceStore((state) => state.zenMode)
  const [quickOpen, setQuickOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [pendingChord, setPendingChord] = useState(false)

  const fileIds = useMemo(
    () => new Set(Object.values(nodes).filter((node) => node.type === 'file').map((file) => file.id)),
    [nodes],
  )

  useEffect(() => {
    defineOlympiadThemes()
  }, [])

  useEffect(() => {
    modelRegistry.prune(fileIds)
  }, [fileIds])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    if (!notice) return
    const timeout = window.setTimeout(() => setNotice(null), 3200)
    return () => window.clearTimeout(timeout)
  }, [notice])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (useCMSSession.getState().switching) { event.preventDefault(); return }
      const mod = event.metaKey || event.ctrlKey
      const key = event.key.toLocaleLowerCase()

      if (pendingChord) {
        setPendingChord(false)
        if (key === 'z') {
          event.preventDefault()
          useWorkspaceStore.getState().toggleZenMode()
        }
        return
      }

      if (mod && key === 'k') {
        setPendingChord(true)
        window.setTimeout(() => setPendingChord(false), 1500)
        return
      }
      if (mod && key === 'p') {
        event.preventDefault()
        setQuickOpen(true)
      } else if (mod && key === 'b') {
        event.preventDefault()
        const store = useWorkspaceStore.getState()
        store.setExplorerVisible(!store.explorerVisible)
      } else if (mod && key === 'j') {
        event.preventDefault()
        const store = useWorkspaceStore.getState()
        store.setBottomPanelVisible(!store.bottomPanelVisible)
      } else if (mod && event.key === '\\') {
        event.preventDefault()
        useWorkspaceStore.getState().toggleSplit()
      } else if (mod && event.key === ',') {
        event.preventDefault()
        useWorkspaceStore.getState().setActiveView('settings')
      } else if (mod && key === 'w') {
        event.preventDefault()
        const store = useWorkspaceStore.getState()
        const group = store.groups[store.activeGroupId]
        if (group.activeFileId) store.closeTab(group.activeFileId, group.id)
      } else if (mod && key === 's') {
        event.preventDefault()
        void persistence.checkpoint().then(() => setNotice('Local checkpoint committed to IndexedDB.'))
          .catch(() => setNotice('Local save failed. Open synchronization details to export your work.'))
      } else if (mod && event.key === '1') {
        event.preventDefault()
        useWorkspaceStore.getState().setActiveGroup('primary')
      } else if (mod && event.key === '2' && useWorkspaceStore.getState().splitEnabled) {
        event.preventDefault()
        useWorkspaceStore.getState().setActiveGroup('secondary')
      } else if (mod && event.key === 'Enter') {
        event.preventDefault()
        void executions.run()
      } else if (event.key === 'F5') {
        event.preventDefault()
        if (event.shiftKey) { void executions.cancel(); void debugging.stop() }
        else { useWorkspaceStore.getState().setActiveView('run'); void debugging.start() }
      } else if (event.key === 'Escape') {
        setQuickOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [pendingChord])


  return (
    <div className={`app-shell ${cmsEnabled ? 'cms' : ''} ${switchingTask ? 'cms-switching' : ''} ${zenMode ? 'zen' : ''}`}>
      <CMSWorkbench />
      {!zenMode && <Toolbar />}
      <main className="workbench">
        {!zenMode && <ActivityBar />}
        <div className="min-w-0 flex-1">
          <PanelGroup
            direction="horizontal"
            className="h-full"
            onLayout={(sizes) => {
              if (explorerVisible && !zenMode && sizes[0] !== undefined) useWorkspaceStore.getState().setExplorerSize(sizes[0])
            }}
          >
            {explorerVisible && !zenMode && (
              <>
                <Panel defaultSize={explorerSize} minSize={14} maxSize={36} order={1}>
                  <Sidebar />
                </Panel>
                <PanelResizeHandle className="sidebar-resize-handle" />
              </>
            )}
            <Panel minSize={45} order={2}>
              <PanelGroup
                direction="vertical"
                className="h-full"
                onLayout={(sizes) => {
                  if (bottomPanelVisible && !zenMode && sizes[1] !== undefined) useWorkspaceStore.getState().setBottomPanelSize(sizes[1])
                }}
              >
                <Panel minSize={35}>
                  {switchingTask ? <div className="task-switch-progress" role="status">Opening problem…</div> : <EditorArea key={workspaceId} />}
                </Panel>
                {bottomPanelVisible && !zenMode && (
                  <>
                    <PanelResizeHandle className="bottom-resize-handle" />
                    <Panel defaultSize={Math.max(32, bottomPanelSize)} minSize={26} maxSize={55}>
                      <BottomPanel />
                    </Panel>
                  </>
                )}
              </PanelGroup>
            </Panel>
          </PanelGroup>
        </div>
      </main>
      {!zenMode && <StatusBar />}
      <PersistencePanel />
      {quickOpen && <QuickOpen onClose={() => setQuickOpen(false)} />}
      {pendingChord && <div className="chord-hint">(Ctrl/Cmd+K) was pressed. Waiting for second key…</div>}
      {notice && <div className="toast" role="status">{notice}</div>}
    </div>
  )
}
