import { Construction } from 'lucide-react'

interface PhasePanelProps {
  title: string
  eyebrow: string
  body: string
}

export function PhasePanel({ title, eyebrow, body }: PhasePanelProps) {
  return (
    <aside className="sidebar-panel">
      <div className="sidebar-title">{title}</div>
      <div className="m-4 border border-[var(--border)] bg-[var(--surface-raised)] p-4">
        <Construction className="mb-3 h-5 w-5 text-[var(--accent)]" />
        <p className="mb-2 text-[10px] font-semibold tracking-[0.12em] text-[var(--muted)]">{eyebrow}</p>
        <p className="text-xs leading-5 text-[var(--fg)]">{body}</p>
      </div>
    </aside>
  )
}
