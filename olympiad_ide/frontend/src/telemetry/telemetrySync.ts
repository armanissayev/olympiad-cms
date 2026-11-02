import { database, type WorkspaceDatabase } from '../persistence/database'
import { retryDelay, WorkspaceAPI } from '../persistence/api'
import { telemetry, useTelemetryStatus, type TelemetryCollector } from './collector'
import { canonical, digest } from './replayEngine'
import type { Acknowledgement, BatchBody, DurableBatch, TelemetrySession } from './types'

export const uploadConfig = { intervalMs: 2000, maxEvents: 200, maxBodyBytes: 256_000, maxBatchBytes: 8_000_000 }
export class TelemetrySync {
  private running = false
  private stopped = false
  private timer?: ReturnType<typeof setTimeout>
  private attempt = 0
  constructor(readonly db: WorkspaceDatabase = database, readonly collector: TelemetryCollector = telemetry, readonly api = new WorkspaceAPI()) {}
  start() { this.stopped = false; this.schedule(0) }
  stop() { this.stopped = true; clearTimeout(this.timer) }
  async suspend() { this.stop(); while (this.running) await new Promise(resolve => setTimeout(resolve, 10)) }
  private schedule(delay: number) { if (!this.stopped) { clearTimeout(this.timer); this.timer = setTimeout(() => void this.sync(), delay) } }
  async buildBatch(session: TelemetrySession): Promise<DurableBatch | null> {
    const pending = await this.db.telemetryBatches.where('sessionId').equals(session.id).filter(b => !b.acknowledged).sortBy('firstSequence')
    if (pending[0]) return pending[0]
    const candidates = await this.db.telemetryEvents.where('[sessionId+sequence]').between([session.id, session.lastAck + 1], [session.id, Infinity]).limit(uploadConfig.maxEvents).toArray()
    if (candidates[0] && candidates[0].sequence !== session.lastAck + 1) throw new Error(`Missing Events: expected ${session.lastAck + 1}`)
    const body: BatchBody = { id: crypto.randomUUID(), sessionId: session.id, events: [], checkpoints: [] }
    let size = 200
    for (const event of candidates) {
      const bytes = canonical(event).length + 1
      if (body.events.length && size + bytes > uploadConfig.maxBodyBytes) break
      if (size + bytes > uploadConfig.maxBatchBytes) throw new Error('Single event exceeds transport assembly limit; data retained for export')
      body.events.push(event); size += bytes
    }
    const last = body.events.at(-1)?.sequence ?? session.lastAck
    const checkpoints = await this.db.telemetryCheckpoints.where('sessionId').equals(session.id).filter(c => c.sequence <= last).sortBy('sequence')
    const sent = new Set((await this.db.telemetryBatches.where('sessionId').equals(session.id).toArray()).filter(b => b.acknowledged).flatMap(b => b.body.checkpoints.map(c => c.id)))
    for (const checkpoint of checkpoints) {
      if (checkpoint.sequence === 0 || sent.has(checkpoint.id)) continue
      const bytes = canonical(checkpoint).length
      if (bytes + 200 > uploadConfig.maxBatchBytes) throw new Error('Checkpoint exceeds transport assembly limit; data retained for export')
      if (size + bytes > uploadConfig.maxBatchBytes) break
      body.checkpoints.push(checkpoint); size += bytes
    }
    if (!body.events.length && !body.checkpoints.length) return null
    if (canonical(body).length > uploadConfig.maxBatchBytes) throw new Error('Batch exceeds transport limit')
    const batch: DurableBatch = { id: body.id, sessionId: session.id, firstSequence: body.events[0]?.sequence ?? last, body, digest: await digest(body), acknowledged: false }
    await this.db.telemetryBatches.add(batch)
    return batch
  }
  private async send(batch: DurableBatch): Promise<Acknowledgement> {
    const serialized = canonical(batch.body)
    if (serialized.length + 100 <= uploadConfig.maxBodyBytes) return this.api.request('/telemetry/batches', { method: 'POST', body: JSON.stringify({ ...batch.body, digest: batch.digest }) })
    // A large transaction stays ONE event. Only the transport is chunked; durable server staging is idempotent.
    const chunkSize = Math.floor(uploadConfig.maxBodyBytes / 8), total = Math.ceil(serialized.length / chunkSize)
    let acknowledgement: Acknowledgement | null = null
    for (let index = 0; index < total; index++) {
      const result = await this.api.request<{ acknowledgement: Acknowledgement | null }>(`/telemetry/batches/${batch.id}/chunks`, { method: 'POST', body: JSON.stringify({ sessionId: batch.sessionId, digest: batch.digest, index, total, data: serialized.slice(index * chunkSize, (index + 1) * chunkSize) }) })
      if (result.acknowledgement) { acknowledgement = result.acknowledgement; break }
    }
    if (!acknowledgement) throw new Error('Chunked batch not committed')
    return acknowledgement
  }
  async sync() {
    if (this.running || this.stopped) return
    this.running = true
    try {
      if (navigator.locks) await navigator.locks.request('olympiad-telemetry-sync', { ifAvailable: true }, lock => lock ? this.upload() : undefined)
      else await this.upload()
    } finally { this.running = false; this.schedule(this.attempt ? retryDelay(this.attempt) : uploadConfig.intervalMs) }
  }
  private async upload() {
    try {
      if (!navigator.onLine) { useTelemetryStatus.setState({ status: this.collector.session?.error ? 'Recording Error' : 'Recording Locally' }); return }
      await this.collector.flush()
      await this.api.session()
      const policy = await this.api.request<{ retentionDays: number }>('/telemetry/policy')
      useTelemetryStatus.setState({ retentionDays: policy.retentionDays })
      const sessions = await this.db.telemetrySessions.orderBy('startedAt').toArray()
      for (const session of sessions) {
        if (this.stopped) break
        if (!session.registered) {
          await this.api.request('/telemetry/sessions', { method: 'POST', body: JSON.stringify({ id: session.id, workspaceId: session.workspaceId, startedAt: session.startedAt, initial: session.initial }) })
          await this.db.telemetrySessions.update(session.id, { registered: true, retentionDays: policy.retentionDays })
        }
        // Bound each turn; current and old offline sessions are all retried on subsequent turns.
        for (let turn = 0; turn < 4; turn++) {
          if (this.stopped) break
          const latest = (await this.db.telemetrySessions.get(session.id))!
          const batch = await this.buildBatch(latest)
          if (!batch) break
          if (!this.collector.session.error) useTelemetryStatus.setState({ status: 'Uploading' })
          const ack = await this.send(batch)
          const expected = batch.body.events.at(-1)?.sequence ?? latest.lastAck
          const current = (await this.db.telemetrySessions.get(session.id))!
          if (ack.batchId !== batch.id || ack.sessionId !== session.id || ack.digest !== batch.digest || ack.lastSequence < expected || ack.lastSequence > current.lastSequence) throw new Error('Invalid telemetry acknowledgement')
          await this.db.transaction('rw', this.db.telemetryBatches, this.db.telemetrySessions, this.db.telemetryAcknowledgements, async () => {
            await this.db.telemetryBatches.update(batch.id, { acknowledged: true })
            await this.db.telemetryAcknowledgements.put(ack)
            const previous = (await this.db.telemetrySessions.get(session.id))!
            await this.db.telemetrySessions.update(session.id, { lastAck: Math.max(previous.lastAck, ack.lastSequence) })
          })
          if (session.id === this.collector.session.id) this.collector.session.lastAck = Math.max(this.collector.session.lastAck, ack.lastSequence)
        }
        // Completion/interruption metadata can change after last event committed; retry this idempotently too.
        const latest = (await this.db.telemetrySessions.get(session.id))!
        if (session.id === this.collector.session.id) this.collector.session.lastAck = latest.lastAck
        if (latest.completedAt || latest.integrity !== 'Complete') await this.api.request(`/telemetry/sessions/${session.id}/close`, { method: 'POST', body: JSON.stringify({ completedAt: latest.completedAt, integrity: latest.integrity, lastSequence: latest.lastSequence }) })
      }
      this.attempt = 0
      this.collector.uplinkAvailable = true
      this.collector.refresh()
      if (!this.collector.session.error) useTelemetryStatus.setState({ status: this.collector.session.lastSequence === this.collector.session.lastAck ? 'Synced' : 'Recording', error: null })
    } catch (error) {
      this.collector.uplinkAvailable = false
      this.attempt++
      const message = error instanceof Error ? error.message : String(error)
      const invalid = /Missing Events|Revision Mismatch|Checkpoint Mismatch|Invalid Event|exceeds.*limit/.test(message)
      if (invalid) { this.collector.fail(error); if (message.includes('Missing Events')) useTelemetryStatus.setState(s => ({ gaps: s.gaps + 1 })) }
      else useTelemetryStatus.setState({ status: this.collector.session?.error ? 'Recording Error' : 'Recording Locally', error: message })
    }
  }
}
export let telemetrySync = new TelemetrySync()
export function bindTelemetrySync(next: TelemetrySync) { telemetrySync = next }
