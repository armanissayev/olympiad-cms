import { createRoot } from 'react-dom/client'
import { initializeCMS } from './cms/session'
import './index.css'
import './cms/cms.css'

void initializeCMS().then(() => import('./boot')).catch((error: unknown) => {
  createRoot(document.getElementById('root')!).render(<main className="cms-entry"><h1>Olympiad IDE</h1><p>{error instanceof Error ? error.message : 'CMS authentication is unavailable.'}</p><p>Your existing browser storage has not been deleted. Return after signing in through the CMS participant page.</p><a href="/">Open CMS participant page</a><button onClick={() => location.reload()}>Retry</button></main>)
})
