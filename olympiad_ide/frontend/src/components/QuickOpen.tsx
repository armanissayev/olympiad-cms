import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { FileIcon } from './FileIcon'
import { getNodePath, useWorkspaceStore } from '../store/workspaceStore'

interface QuickOpenProps {
  onClose: () => void
}

export function QuickOpen({ onClose }: QuickOpenProps) {
  const [query, setQuery] = useState('')
  const nodes = useWorkspaceStore((state) => state.nodes)
  const files = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    return Object.values(nodes)
      .filter((node) => node.type === 'file')
      .filter((file) => !normalized || getNodePath(nodes, file.id).toLocaleLowerCase().includes(normalized))
      .slice(0, 20)
  }, [nodes, query])

  const open = (fileId: string) => {
    useWorkspaceStore.getState().openFile(fileId)
    onClose()
  }

  return (
    <div className="overlay" onMouseDown={onClose} role="presentation">
      <div className="quick-open" onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="Quick Open">
        <div className="quick-input-wrap">
          <Search className="h-4 w-4 text-[var(--muted)]" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search files by name"
            aria-label="Search files by name"
            autoFocus
            onKeyDown={(event) => {
              if (event.key === 'Escape') onClose()
              if (event.key === 'Enter' && files[0]) open(files[0].id)
            }}
          />
        </div>
        <div className="max-h-80 overflow-auto py-1">
          {files.map((file, index) => (
            <button key={file.id} className={`quick-result ${index === 0 ? 'selected' : ''}`} onClick={() => open(file.id)}>
              <FileIcon name={file.name} />
              <span className="truncate">{file.name}</span>
              <span className="ml-auto truncate text-[11px] text-[var(--muted)]">{getNodePath(nodes, file.id)}</span>
            </button>
          ))}
          {files.length === 0 && <p className="p-4 text-xs text-[var(--muted)]">No matching files.</p>}
        </div>
      </div>
    </div>
  )
}
