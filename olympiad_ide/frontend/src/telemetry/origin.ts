// Tiny dependency-free boundary shared with Phase 2; no telemetry dependency in its journal.
let current: string | null = null
export const documentOrigin = () => current
export function withDocumentOrigin<T>(origin: string, action: () => T): T {
  const previous = current
  current = origin
  try { return action() } finally { current = previous }
}
