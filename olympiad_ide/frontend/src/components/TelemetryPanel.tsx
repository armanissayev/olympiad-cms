import { useState } from 'react'
import { Radio, X } from 'lucide-react'
import { telemetry, useTelemetryStatus } from '../telemetry/collector'
import { telemetrySync } from '../telemetry/telemetrySync'

export function TelemetryIndicator() {
  const state = useTelemetryStatus()
  const [open, setOpen] = useState(false)
  const exportRecording = async () => {
    const archive = await telemetry.export()
    const url = URL.createObjectURL(new Blob([JSON.stringify(archive)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = `olympiad-recording-${state.sessionId}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <>
    <button className="sync-indicator" aria-label={`Telemetry: ${state.status}`} onClick={() => setOpen(!open)}><Radio size={13} />{state.status}</button>
    <div className="telemetry-disclosure">
      <button onClick={() => setOpen(true)}>Editor recording enabled · input, source changes and navigation · privacy &amp; diagnostics</button>
      {(state.status === 'Recording Error' || state.status === 'Recording Interrupted') && <span role="alert">{state.status} — {state.error}. Export your recording; this session is incomplete.</span>}
    </div>
    {open && <section className="sync-popover telemetry-popover" role="dialog" aria-label="Recording diagnostics">
      <header className="flex items-center justify-between"><strong>{state.status}</strong><button aria-label="Close recording diagnostics" onClick={() => setOpen(false)}><X size={15} /></button></header>
      <p>Input in Monaco code editors, source changes (including inserted paste), cursor/selection, file operations, focus and page visibility are recorded for editing-history replay and future behavioral research. No OS-wide keys, password fields, other forms or raw clipboard contents are collected.</p>
      <p>Records are buffered in this browser’s IndexedDB and uploaded to the authenticated development backend. Only the owning development session can read them through the API; deployment/database administrators may access stored data. Development identity cookies are not production accounts.</p>
      <p>Server retention: {state.retentionDays} days (last fetched policy, or the 30-day development default while offline), configurable by administrators. Expiration requires maintenance to run. Browser copies are retained until explicit safe maintenance/browser data clearing; unsent data is never automatically deleted. Browser storage may be evicted. Hashes verify consistency, not honesty.</p>
      <dl className="telemetry-diagnostics"><dt>Session</dt><dd data-testid="telemetry-session">{state.sessionId}</dd><dt>Last sequence</dt><dd>{state.sequence}</dd><dt>Pending events</dt><dd>{state.pending}</dd><dt>Last acknowledged</dt><dd>{state.lastAck}</dd><dt>Detected gaps</dt><dd>{state.gaps}</dd><dt>Last checkpoint</dt><dd>{state.checkpoint}</dd></dl>
      {state.error && <p className="text-[#f48771]">{state.error}</p>}
      <div className="flex gap-2"><button className="tool-button" onClick={() => void telemetry.flush().then(() => telemetrySync.sync()).catch(error => telemetry.fail(error))}>Retry upload</button><button className="tool-button" onClick={() => void exportRecording()}>Export recording</button></div>
      <p>An ordinary reload starts a new clock/sequence session and retries old durable batches. Events still in memory at crash/unload can be lost; interrupted histories are labeled, not declared complete.</p>
    </section>}
  </>
}
