import { expect, it, vi } from 'vitest'
import { WorkspaceAPI } from './api'

it('workspace and telemetry establish a single cookie identity during concurrent first startup', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ identityId: 'shared-cookie-owner' }), { headers: { 'Content-Type': 'application/json' } }))
  try {
    const workspace = new WorkspaceAPI(), telemetry = new WorkspaceAPI()
    const [first, second] = await Promise.all([workspace.session(), telemetry.session()])
    expect(first).toEqual(second)
    expect(fetch).toHaveBeenCalledTimes(1)
    await workspace.session()
    expect(fetch).toHaveBeenCalledTimes(2)
  } finally { fetch.mockRestore() }
})
