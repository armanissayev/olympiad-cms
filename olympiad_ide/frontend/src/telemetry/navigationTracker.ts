import type { editor } from 'monaco-editor'
import { telemetry, type TelemetryCollector } from './collector'
import { keyboardPayload } from './keyboardTracker'
import type { Range } from './types'
const range = (r: Range): Range => ({ startLineNumber: r.startLineNumber, startColumn: r.startColumn, endLineNumber: r.endLineNumber, endColumn: r.endColumn })

/** All listeners belong to this pane, except content, which is tracked on the shared model. No global key listeners. */
export function attachPaneTelemetry(instance: editor.IStandaloneCodeEditor, paneId: string, file: () => string | null, collector: TelemetryCollector = telemetry): () => void {
  let composing = false
  const subscriptions = [
    instance.onKeyDown(e => { const id = file(); if (id && instance.hasTextFocus()) collector.key('KEY_DOWN', id, keyboardPayload(e.browserEvent, paneId, composing)) }),
    instance.onKeyUp(e => { const id = file(); if (id && instance.hasTextFocus()) collector.key('KEY_UP', id, keyboardPayload(e.browserEvent, paneId, composing)) }),
    instance.onDidCompositionStart(() => { composing = true; collector.record('COMPOSITION_START', file(), { paneId }) }),
    instance.onDidCompositionEnd(() => { composing = false; collector.record('COMPOSITION_END', file(), { paneId }) }),
    instance.onDidFocusEditorText(() => collector.record('EDITOR_FOCUS', file(), { paneId })),
    instance.onDidBlurEditorText(() => collector.record('EDITOR_BLUR', file(), { paneId })),
    instance.onDidChangeCursorPosition(e => collector.record('CURSOR_MOVED', file(), { paneId, lineNumber: e.position.lineNumber, column: e.position.column, source: e.source })),
    instance.onDidChangeCursorSelection(e => collector.record('SELECTION_CHANGED', file(), { paneId, selections: [e.selection, ...e.secondarySelections].map(range), source: e.source })),
    instance.onDidPaste(e => {
      const id = file(), model = instance.getModel(), transaction = id ? collector.transactions.get(id) : undefined
      collector.record('PASTE', id, { paneId, transactionId: model && transaction?.version === model.getVersionId() ? transaction.transactionId : null, range: range(e.range) })
    }),
    instance.onDidChangeModel(() => {
      const id = file(), model = instance.getModel()
      if (id && model) collector.trackModel(id, model)
    }),
  ]
  return () => subscriptions.forEach(subscription => subscription.dispose())
}
