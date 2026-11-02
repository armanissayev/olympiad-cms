import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { offlineShell } from './build/offlineShell'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const cms = env.VITE_CMS_MODE !== 'false'
  const base = env.VITE_IDE_BASE ?? (cms ? '/ide/' : '/')
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(base) || (cms && base === '/')) throw new Error('CMS IDE base must be a dedicated absolute directory path, e.g. /ide/')
  return {
    base,
    define: { 'import.meta.env.VITE_CMS_MODE': JSON.stringify(String(cms)) },
    plugins: [react(), offlineShell()],
    server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
    preview: { proxy: { '/api': 'http://127.0.0.1:8000' } },
    build: { target: 'es2022' },
  }
})
