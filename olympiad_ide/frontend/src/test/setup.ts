import { beforeEach } from 'vitest'
import 'fake-indexeddb/auto'

beforeEach(() => {
  window.localStorage.clear()
})
