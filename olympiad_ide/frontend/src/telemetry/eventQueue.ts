import type { WorkspaceDatabase } from '../persistence/database'
import type { Checkpoint, TelemetryEvent, TelemetrySession } from './types'

/** Required events are never compacted. Failed writes retain the exact in-memory prefix. */
export class EventQueue {
  readonly pending: TelemetryEvent[] = []
  readonly checkpoints: Checkpoint[] = []
  private tail: Promise<void> = Promise.resolve()
  private timer: ReturnType<typeof setTimeout> | undefined
  failed = false
  constructor(readonly db: WorkspaceDatabase, readonly session: TelemetrySession, private changed: () => void, private failure: (error: unknown) => void) {}
  async initialize() {
    await this.db.transaction('rw', this.db.telemetrySessions, this.db.telemetryCheckpoints, async () => {
      await this.db.telemetrySessions.add(this.session)
      await this.db.telemetryCheckpoints.add(this.session.initial)
    })
  }
  append(event: TelemetryEvent) {
    this.pending.push(event)
    this.changed()
    if (!this.timer && !this.failed) this.timer = setTimeout(() => { this.timer = undefined; void this.flush().catch(() => undefined) }, 16)
  }
  checkpoint(checkpoint: Checkpoint) { this.checkpoints.push(checkpoint); return this.flush() }
  flush(): Promise<void> {
    clearTimeout(this.timer); this.timer = undefined
    const run = this.tail.catch(() => undefined).then(async () => {
      const events = this.pending.slice(), checkpoints = this.checkpoints.slice()
      try {
        await this.db.transaction('rw', this.db.telemetrySessions, this.db.telemetryEvents, this.db.telemetryCheckpoints, async () => {
          if (!await this.db.telemetrySessions.get(this.session.id)) {
            await this.db.telemetrySessions.add(this.session)
            await this.db.telemetryCheckpoints.put(this.session.initial)
          }
          await this.db.telemetryEvents.bulkAdd(events)
          await this.db.telemetryCheckpoints.bulkPut(checkpoints)
          await this.db.telemetrySessions.update(this.session.id, {
            lastSequence: events.at(-1)?.sequence ?? this.session.lastSequence,
            completedAt: this.session.completedAt, integrity: this.session.integrity, error: this.session.error,
          })
        })
        this.pending.splice(0, events.length); this.checkpoints.splice(0, checkpoints.length)
        this.failed = false; this.changed()
      } catch (error) { this.failed = true; this.failure(error); throw error }
    })
    this.tail = run
    return run
  }
  dispose() { clearTimeout(this.timer) }
}
