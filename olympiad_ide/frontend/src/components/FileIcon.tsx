import { Braces, File, FileCode2, FileInput, FileOutput, Hash } from 'lucide-react'

interface FileIconProps {
  name: string
  className?: string
}

export function FileIcon({ name, className = 'h-4 w-4' }: FileIconProps) {
  const extension = name.split('.').pop()?.toLowerCase()
  if (['cpp', 'cc', 'cxx', 'h', 'hpp'].includes(extension ?? '')) {
    return <FileCode2 className={`${className} text-[#519aba]`} aria-hidden="true" />
  }
  if (extension === 'py') return <Braces className={`${className} text-[#dcdcaa]`} aria-hidden="true" />
  if (extension === 'java') return <Hash className={`${className} text-[#e06c75]`} aria-hidden="true" />
  if (extension === 'in') return <FileInput className={`${className} text-[#89d185]`} aria-hidden="true" />
  if (extension === 'out') return <FileOutput className={`${className} text-[#c586c0]`} aria-hidden="true" />
  return <File className={`${className} text-[var(--muted)]`} aria-hidden="true" />
}
