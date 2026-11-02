import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './editor/monaco'
import './index.css'
import App from './App'
import { persistence } from './persistence/controller'
import { usePersistenceStatus } from './persistence/status'
import { registerOfflineShell } from './persistence/offlineShell'
import { telemetry, useTelemetryStatus } from './telemetry/collector'
import { telemetrySync, uploadConfig } from './telemetry/telemetrySync'
import { executions } from './execution/controller'

await persistence.start()
await telemetry.start()
telemetrySync.start()
useTelemetryStatus.subscribe((next, previous) => {
  if (next.pending >= uploadConfig.maxEvents && previous.pending < uploadConfig.maxEvents) void telemetrySync.sync()
})
registerOfflineShell()

const flush = () => { void persistence.flush().catch(() => undefined); void telemetry.flush().catch(error => telemetry.fail(error)) }
window.addEventListener('online', () => { void persistence.syncNow(); void telemetrySync.sync() })
window.addEventListener('pagehide', flush)
document.addEventListener('visibilitychange', () => {
  const hidden = document.visibilityState === 'hidden'
  telemetry.record(hidden ? 'PAGE_HIDDEN' : 'PAGE_VISIBLE', null, {})
  if (hidden) { void telemetry.checkpoint('page-hidden'); flush() }
})
window.addEventListener('beforeunload', (event) => {
  // Async work is already enqueued; this warning does not promise unload-time durability.
  if (usePersistenceStatus.getState().localPending || usePersistenceStatus.getState().error || telemetry.queue.pending.length || telemetry.session.error) {
    event.preventDefault()
    event.returnValue = ''
  }
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
void executions.start()
