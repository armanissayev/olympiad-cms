export interface CMSIdentity { installationId: string; userId: string | number; contestId: string | number; participationId: string | number; principalId: string }
export interface CMSLanguage { id: string; name: string; extension: string; extensions?: string[] }
export interface CMSTask {
  id: number; name: string; title: string; languages: CMSLanguage[]; submissionFormat: string[]
  supported: boolean; customRunSupported?: boolean; customRunReason?: string | null; reason?: string | null; statementUrl: string; submissionsUrl: string
  statements: { language: string; url: string }[]; attachments: { name: string; url: string }[]
}
export interface CMSContext {
  schemaVersion: 1; identity: CMSIdentity; user: { username: string; firstName: string; lastName: string }
  contest: { id: string | number; name: string; description: string }; actualPhase: number
  serverTime: string; phaseEnd: string | null; tasks: CMSTask[]; csrfToken: string
  executionProfileMap?: Record<string, { cmsLanguage: string; enabled: boolean; versionVerification: string; reason: string }>
  links: { login: string; logout: string; fallback: string; announcements: string; clarifications: string }
}
export interface OfficialSource { filename: string; sourceFilename: string; fileId: string; content: string }
export interface OfficialIntent {
  schemaVersion: 1; intentId: string; taskId: number; language: string; files: OfficialSource[]
  snapshotId: string; workspaceId: string; telemetry: { sessionId: string; sequence: number } | null
}
export interface OfficialReceipt {
  schemaVersion: 1; state: 'admitted'; intentId: string; submissionId: string; receivedAt: string; official: boolean
  taskId: number; language: string; files: { filename: string; sourceFilename: string; fileId: string; sha256: string; size: number }[]
  snapshotId: string; workspaceId: string
}
export interface ParticipantStatus {
  status: number; status_text: string; public_score?: number; max_public_score?: number; public_score_message?: string
  score?: number; max_score?: number; score_message?: string; task_public_score?: number; task_tokened_score?: number
  task_score_is_partial?: boolean; detailsText?: string; detailsTruncated?: boolean
  compilation?: { text: string; stdout: string | null; stderr: string | null; stdoutTruncated: boolean; stderrTruncated: boolean; time: number | null; memory: number | null }
}
export interface OfficialHistory { submissionId: string; receivedAt: string; official: boolean; language: string; status: ParticipantStatus; cwsUrl: string }
export interface StoredIntent {
  intentId: string; principalId: string; taskId: number; body: OfficialIntent; hashes: Record<string, string>
  correlation?: { state: 'verified' | 'mismatch' | 'unknown'; reason: string }
  state: 'confirmed' | 'pending' | 'admitted' | 'rejected' | 'unknown'; createdAt: string; receipt?: OfficialReceipt; error?: string
}
