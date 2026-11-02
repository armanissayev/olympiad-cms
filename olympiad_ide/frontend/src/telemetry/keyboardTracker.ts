import type { EventPayloads } from './types'
export function keyboardPayload(event: KeyboardEvent, paneId: string, composing = false): EventPayloads['KEY_DOWN'] {
  return { paneId, code: event.code, key: event.key, ctrl: event.ctrlKey, alt: event.altKey, shift: event.shiftKey, meta: event.metaKey, repeat: event.repeat, composing: composing || event.isComposing }
}
