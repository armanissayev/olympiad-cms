export type Language = 'cpp17' | 'cpp20' | 'python3' | 'java17'
export interface RunConfiguration { kind: 'configuration'; id: string; name: string; language: Language; entryPoint: string; includedFiles: string[]; compilerProfile: 'release'; mainClass: string | null; defaultTestId: string | null }
export interface TestCase { kind: 'test'; id: string; name: string; stdin: string; expectedStdout: string | null }
export type ResourceValue = RunConfiguration | TestCase
export interface RemoteResource { id: string; workspaceId: string; revision: number; value: ResourceValue; deleted: boolean }
export interface LocalResource extends RemoteResource { localVersion: number; conflict?: RemoteResource }
export interface ResourceOperation { sequence?: number; operationId: string; resourceId: string; workspaceId: string; baseRevision: number; value: ResourceValue; deleted: boolean; localVersion: number; status: 'pending' | 'sending' }
export interface SourceFile { id: string; path: string; content: string }
export interface Submission { id: string; workspaceId: string; configuration: RunConfiguration; files: SourceFile[]; sourceHash: string; tests: TestCase[] }
export type JobStatus = 'QUEUED' | 'PREPARING' | 'COMPILING' | 'RUNNING' | 'FINISHED' | 'COMPILATION_ERROR' | 'RUNTIME_ERROR' | 'TIME_LIMIT_EXCEEDED' | 'MEMORY_LIMIT_EXCEEDED' | 'OUTPUT_LIMIT_EXCEEDED' | 'CANCELLED' | 'INFRASTRUCTURE_ERROR'
export const terminalStatuses = new Set<JobStatus>(['FINISHED', 'COMPILATION_ERROR', 'RUNTIME_ERROR', 'TIME_LIMIT_EXCEEDED', 'MEMORY_LIMIT_EXCEEDED', 'OUTPUT_LIMIT_EXCEEDED', 'CANCELLED', 'INFRASTRUCTURE_ERROR'])
export interface CaseResult { testId: string; name: string; status: JobStatus; stdout: string; stderr: string; expectedStdout: string | null; verdict: 'Accepted' | 'Wrong Answer' | 'Not Compared' | 'Not Executed'; exitCode: number | null; cpuTime: number | null; wallTime: number | null; peakMemoryKiB: number | null }
export interface JobResult { status: JobStatus; compilationOutput: string; compilationSeconds: number | null; toolchainVersion: string; cases: CaseResult[]; error: string | null }
export interface Job { id: string; workspaceId: string; snapshotId: string; sourceHash: string; sourceManifest: { id: string; path: string }[]; configuration: RunConfiguration; status: JobStatus; createdAt: string; startedAt: string | null; completedAt: string | null; cancelRequested: boolean; lastSequence: number; result: JobResult | null; tests: TestCase[] }
export interface JobEvent { sequence: number; timestamp: string; eventType: 'STATUS' | 'OUTPUT' | 'CASE_RESULT' | 'RESULT'; status?: JobStatus; stream?: 'compiler' | 'stdout' | 'stderr'; text?: string; case?: CaseResult }
