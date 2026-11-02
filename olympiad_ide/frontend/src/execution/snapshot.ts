import { getNodePath, useWorkspaceStore } from '../store/workspaceStore'
import { modelRegistry } from '../editor/modelRegistry'
import { digest } from '../telemetry/replayEngine'
import type { RunConfiguration, Submission, TestCase } from './types'

export function defaultConfiguration(): RunConfiguration {
  const state = useWorkspaceStore.getState(), file = state.nodes[state.groups[state.activeGroupId].activeFileId ?? '']
  if (file?.type !== 'file' || file.language === 'plaintext') throw new Error('Open a C++, Python or Java file to run it.')
  const language = file.language === 'cpp' ? 'cpp20' : file.language === 'python' ? 'python3' : 'java17'
  const includedFiles = [file.id]
  const packageName = file.language === 'java' ? /\bpackage\s+([\w.]+)\s*;/.exec(modelRegistry.get(file.id)?.getValue() ?? file.content)?.[1] : undefined
  return { kind: 'configuration', id: crypto.randomUUID(), name: `Run ${file.name}`, language, entryPoint: file.id, includedFiles, compilerProfile: 'release', mainClass: language === 'java17' ? `${packageName ? packageName + '.' : ''}${file.name.replace(/\.java$/, '')}` : null, defaultTestId: null }
}

/** Capture synchronously BEFORE awaiting hashing/network. Live models include not-yet-synchronized text. */
export async function captureSubmission(configuration: RunConfiguration, tests: TestCase[]): Promise<Submission> {
  const state = useWorkspaceStore.getState()
  const capturedConfiguration = structuredClone(configuration)
  const capturedTests = structuredClone(tests)
  if (!configuration.includedFiles.includes(configuration.entryPoint)) throw new Error('Entry point must be included in the source manifest')
  const files = configuration.includedFiles.map(id => {
    const node = state.nodes[id]
    if (node?.type !== 'file') throw new Error('A configured source file was deleted; update the configuration')
    return { id, path: getNodePath(state.nodes, id), content: modelRegistry.get(id)?.getValue() ?? node.content }
  }).sort((a, b) => a.id < b.id ? -1 : 1)
  return { id: crypto.randomUUID(), workspaceId: state.workspace.id, configuration: capturedConfiguration, files, tests: capturedTests, sourceHash: await digest({ files, configuration: capturedConfiguration }) }
}
