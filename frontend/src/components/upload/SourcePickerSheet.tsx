import { ChevronRightIcon, FileIcon, FileVideoIcon, FolderIcon, FolderOpenIcon } from 'lucide-react'
import { useState } from 'react'

import { useBrowseDisk, useDisks } from '@/api/hooks/disks'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import { cn } from '@/lib/utils'

export interface UploadSource {
  diskId: number
  relativePath: string
  isDir: boolean
}

// Stesse estensioni di nazgarr/core/file_types.py, solo per l'icona.
const VIDEO_EXTENSIONS = ['.mkv', '.mp4', '.avi', '.m2ts', '.ts', '.wmv', '.mov']
const isVideo = (name: string) => VIDEO_EXTENSIONS.some((ext) => name.toLowerCase().endsWith(ext))

function join(parent: string, name: string) {
  return parent ? `${parent}/${name}` : name
}

/** Una cartella del disco, caricata solo quando la si apre: lo stesso
 * aspetto della vista a cartelle (components/FileTree.tsx), ma sul disco
 * vero (/api/disks/{id}/browse), non sui file già scansionati, così si
 * può scegliere anche un file appena copiato. */
function DirectoryRows({
  diskId,
  path,
  depth,
  selected,
  onSelect,
}: {
  diskId: number
  path: string
  depth: number
  selected: string | null
  onSelect: (relativePath: string, isDir: boolean) => void
}) {
  const { data, isPending, isError } = useBrowseDisk(diskId, path)
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const indent = { paddingLeft: `${depth * 1.25 + 0.5}rem` }

  if (isPending) return <p className="py-1.5 text-xs text-muted-foreground" style={indent}>{t('common.loading')}</p>
  if (isError) return <p className="py-1.5 text-xs text-destructive" style={indent}>{t('disks.cannotReadFolder')}</p>

  // Cartelle prima dei file, poi alfabetico (come la vista a cartelle).
  const entries = [...(data?.entries ?? [])].sort(
    (a, b) => Number(b.is_dir) - Number(a.is_dir) || a.name.localeCompare(b.name),
  )
  if (entries.length === 0) {
    return <p className="py-1.5 text-xs text-muted-foreground" style={indent}>{t('disks.emptyFolder')}</p>
  }

  const toggle = (name: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })

  return (
    <>
      {entries.map((entry) => {
        const relativePath = join(path, entry.name)
        const isOpen = open.has(entry.name)
        const isSelected = selected === relativePath
        return (
          <div key={entry.name}>
            <div
              role="button"
              tabIndex={0}
              aria-selected={isSelected}
              className={cn(
                'flex cursor-pointer items-center gap-1.5 rounded-sm py-1.5 pr-2 font-mono text-xs hover:bg-muted',
                isOpen && 'bg-primary/5',
                isSelected && 'bg-primary/15 ring-1 ring-primary/40 hover:bg-primary/20',
              )}
              style={indent}
              onClick={() => onSelect(relativePath, entry.is_dir)}
              onDoubleClick={() => entry.is_dir && toggle(entry.name)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSelect(relativePath, entry.is_dir)
                if (entry.is_dir && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) toggle(entry.name)
              }}
            >
              {entry.is_dir ? (
                <>
                  <button
                    type="button"
                    aria-label={isOpen ? t('upload.picker.collapse') : t('upload.picker.expand')}
                    className="rounded p-0.5 hover:bg-background"
                    onClick={(e) => {
                      e.stopPropagation()
                      toggle(entry.name)
                    }}
                  >
                    <ChevronRightIcon className={cn('size-3.5 transition-transform', isOpen && 'rotate-90')} />
                  </button>
                  {isOpen ? (
                    <FolderOpenIcon className="size-3.5 shrink-0 text-primary" />
                  ) : (
                    <FolderIcon className="size-3.5 shrink-0 text-primary" />
                  )}
                  <span className="truncate font-medium">{entry.name}</span>
                </>
              ) : (
                <>
                  <span className="w-[1.125rem] shrink-0" />
                  {isVideo(entry.name) ? (
                    <FileVideoIcon className="size-3.5 shrink-0 text-muted-foreground" />
                  ) : (
                    <FileIcon className="size-3.5 shrink-0 text-muted-foreground" />
                  )}
                  <span className="truncate">{entry.name}</span>
                  <span className="ml-auto shrink-0 pl-2 text-muted-foreground tabular-nums">
                    {entry.size_bytes != null && formatBytes(entry.size_bytes)}
                  </span>
                </>
              )}
            </div>
            {entry.is_dir && isOpen && (
              <DirectoryRows
                diskId={diskId}
                path={relativePath}
                depth={depth + 1}
                selected={selected}
                onSelect={onSelect}
              />
            )}
          </div>
        )
      })}
    </>
  )
}

export function SourcePickerSheet({
  open,
  onOpenChange,
  initial,
  onSelect,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  initial: UploadSource | null
  onSelect: (source: UploadSource) => void
}) {
  const { data: disks } = useDisks()
  const [diskId, setDiskId] = useState<number | null>(initial?.diskId ?? null)
  const [selected, setSelected] = useState<{ relativePath: string; isDir: boolean } | null>(
    initial ? { relativePath: initial.relativePath, isDir: initial.isDir } : null,
  )
  const activeDiskId = diskId ?? disks?.[0]?.id ?? null

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-5xl">
        <SheetHeader>
          <SheetTitle>{t('upload.picker.title')}</SheetTitle>
          <SheetDescription>{t('upload.picker.description')}</SheetDescription>
        </SheetHeader>
        {disks && disks.length > 1 && (
          <div className="px-4 pb-3">
            <Select
              value={activeDiskId !== null ? String(activeDiskId) : undefined}
              onValueChange={(value) => {
                if (value == null) return
                setDiskId(Number(value))
                setSelected(null)
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder={t('upload.chooseDisk')}>
                  {(value: string | null) => disks.find((d) => String(d.id) === value)?.label}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {disks.map((disk) => (
                  <SelectItem key={disk.id} value={String(disk.id)}>
                    {disk.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-auto border-y px-2 py-1">
          {activeDiskId === null ? (
            <p className="p-3 text-sm text-muted-foreground">{t('upload.picker.noDisks')}</p>
          ) : (
            <DirectoryRows
              key={activeDiskId}
              diskId={activeDiskId}
              path=""
              depth={0}
              selected={selected?.relativePath ?? null}
              onSelect={(relativePath, isDir) => setSelected({ relativePath, isDir })}
            />
          )}
        </div>
        <SheetFooter className="flex-row items-center gap-3">
          <p className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground" title={selected?.relativePath}>
            {selected ? selected.relativePath : t('upload.picker.nothingSelected')}
          </p>
          <Button
            disabled={selected === null || activeDiskId === null}
            onClick={() => {
              if (selected === null || activeDiskId === null) return
              onSelect({ diskId: activeDiskId, ...selected })
              onOpenChange(false)
            }}
          >
            {selected?.isDir ? t('upload.picker.useFolder') : t('upload.picker.useFile')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
