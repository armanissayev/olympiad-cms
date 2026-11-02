import { useMemo, useState } from 'react'
import { Search, X } from 'lucide-react'
import { FileIcon } from '../FileIcon'
import { useWorkspaceStore } from '../../store/workspaceStore'

export function SearchPanel() {
  const [query, setQuery] = useState('')
  const nodes = useWorkspaceStore((state) => state.nodes)
  const results = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return []
    return Object.values(nodes)
      .filter((node) => node.type === 'file')
      .flatMap((file) =>
        file.content.split('\n').flatMap((line, index) =>
          line.toLocaleLowerCase().includes(normalized) ? [{ file, line, lineNumber: index + 1 }] : [],
        ),
      )
      .slice(0, 100)
  }, [nodes, query])

  return (
    <aside className="sidebar-panel">
      <div className="sidebar-title">Search</div>
      <div className="search-box-wrap">
        <Search className="h-3.5 w-3.5 text-[var(--muted)]" />
        <input
          className="search-box"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search workspace"
          autoFocus
          aria-label="Search workspace"
        />
        {query && (
          <button className="tiny-icon-button" onClick={() => setQuery('')} aria-label="Clear search">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <div className="px-3 py-2 text-[11px] text-[var(--muted)]">
        {query ? `${results.length} result${results.length === 1 ? '' : 's'}` : 'Type to search all open workspace files'}
      </div>
      <div className="overflow-auto">
        {results.map(({ file, line, lineNumber }) => (
          <button
            key={`${file.id}:${lineNumber}`}
            className="search-result"
            onClick={() => {
              useWorkspaceStore.getState().openFile(file.id)
              const groupId = useWorkspaceStore.getState().activeGroupId
              const previous = useWorkspaceStore.getState().viewStates[`${groupId}:${file.id}`]
              useWorkspaceStore.getState().setViewState(groupId, file.id, {
                lineNumber,
                column: 1,
                scrollTop: previous?.scrollTop ?? 0,
                scrollLeft: previous?.scrollLeft ?? 0,
              })
            }}
          >
            <span className="flex items-center gap-1.5 text-[11px] text-[var(--fg-strong)]">
              <FileIcon name={file.name} className="h-3.5 w-3.5" />
              {file.name}
              <span className="text-[var(--muted)]">:{lineNumber}</span>
            </span>
            <span className="block truncate pl-5 font-mono text-[11px] text-[var(--muted)]">{line.trim() || ' '}</span>
          </button>
        ))}
      </div>
    </aside>
  )
}
