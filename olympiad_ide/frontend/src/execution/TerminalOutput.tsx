import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { useExecution } from './controller'

export function TerminalOutput() {
  const container = useRef<HTMLDivElement>(null), terminal = useRef<Terminal>(), written = useRef(0)
  const events = useExecution(s => s.events), jobId = useExecution(s => s.job?.id), clearAfter = useExecution(s => s.clearAfter)
  useEffect(() => {
    if (!container.current) return
    const term = new Terminal({ disableStdin: true, convertEol: true, fontSize: 12, fontFamily: 'SFMono-Regular, Consolas, monospace', scrollback: 5000, theme: { background: '#181818', foreground: '#cccccc' } })
    const fit = new FitAddon(); term.loadAddon(fit); term.open(container.current); terminal.current = term
    // Untrusted output must not write the system clipboard or open links/notifications via OSC sequences.
    const handlers = [0, 2, 8, 9, 52, 1337].map(code => term.parser.registerOscHandler(code, () => true))
    const resize = new ResizeObserver(() => { try { fit.fit() } catch { /* Hidden/resizing panel. */ } })
    resize.observe(container.current)
    return () => { resize.disconnect(); handlers.forEach(h => h.dispose()); term.dispose(); terminal.current = undefined }
  }, [])
  useEffect(() => { terminal.current?.reset(); written.current = clearAfter }, [jobId, clearAfter])
  useEffect(() => {
    const term = terminal.current
    if (!term) return
    for (const event of events) {
      if (event.sequence <= written.current) continue
      const following = term.buffer.active.viewportY >= term.buffer.active.baseY
      if (event.eventType === 'OUTPUT') {
        if (event.stream === 'compiler') term.write('\x1b[33m')
        if (event.stream === 'stderr') term.write('\x1b[31m')
        term.write(event.text ?? ''); term.write('\x1b[0m')
      } else if (event.eventType === 'STATUS') term.writeln(`\r\n[${new Date(event.timestamp).toLocaleTimeString()}] ${event.status}`)
      if (following) term.scrollToBottom()
      written.current = event.sequence
    }
  }, [events, jobId, clearAfter])
  return <div ref={container} className="execution-terminal" aria-label="Execution terminal output" />
}
