import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { initialData, useWorkspaceStore } from '../store/workspaceStore'
import { useTelemetryStatus } from '../telemetry/collector'
vi.mock('./session', async load => ({ ...await load<typeof import('./session')>(), cmsEnabled: true }))
vi.mock('../components/explorer/Explorer', () => ({ Explorer: () => <p>Explorer files</p> }))
vi.mock('../history/HistoryPanel', () => ({ HistoryPanel: () => <p>HISTORY REPLAY</p> }))
import { ActivityBar } from '../components/ActivityBar'
import { Sidebar } from '../components/Sidebar'
import { TelemetryIndicator } from '../components/TelemetryPanel'
let host: HTMLDivElement, root: Root
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); useWorkspaceStore.setState({ ...initialData(), activeView: 'history' }); host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals() })
it('hides History and a persisted history selection from the CMS participant chrome', async () => {
  await act(async () => root.render(<><ActivityBar /><Sidebar /></>))
  expect(host.querySelector('[aria-label="History"]')).toBeNull(); expect(host.textContent).not.toContain('HISTORY REPLAY'); expect(host.textContent).toContain('Explorer files')
})
it('shows a quiet disclosure without a recording diagnostics window, errors, exports or action', async () => {
  useTelemetryStatus.setState({ status: 'Recording Error', error: 'File /opt/private.py failed; secret diagnostic' })
  await act(async () => root.render(<TelemetryIndicator />))
  expect(host.textContent).toBe('Editor activity recorded'); expect(host.querySelector('button')).toBeNull(); expect(host.querySelector('[role="dialog"]')).toBeNull()
  expect(host.textContent).not.toMatch(/private|secret|Recording Locally|Session|Export|research/)
})
