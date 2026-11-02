import { create } from 'zustand'
import type { Conflict, SaveStatus } from './types'

interface PersistenceStatus {
  status: SaveStatus
  ready: boolean
  online: boolean
  localPending: number
  pendingOperations: number
  lastSyncedAt: string | null
  error: string | null
  conflict: Conflict | null
  detailsOpen: boolean
}

export const usePersistenceStatus = create<PersistenceStatus>(() => ({
  status: 'Loading', ready: false, online: false, localPending: 0, pendingOperations: 0,
  lastSyncedAt: null, error: null, conflict: null, detailsOpen: false,
}))
