import { FileIcon, FolderIcon, FolderPlusIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useBrowseDisk, useMkdir } from '@/api/hooks/disks'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { t } from '@/lib/i18n'

/** Selettore scoped-per-disco (nazgarr/core/fs_scope.py), due modalità:
 * - "folder" (default): naviga e seleziona la cartella corrente — usato
 *   per una MediaPath o torrents_rel_path (docs/SPEC.md §4).
 * - "file": naviga e seleziona un file specifico — usato per scegliere
 *   il file sorgente di un nuovo upload (docs/SPEC.md §9). Nessun campo
 *   path testo libero in nessuna delle due modalità: un path sbagliato
 *   darebbe solo un 400 al submit. */
export function DiskBrowserDialog({
  diskId,
  open,
  onOpenChange,
  onSelect,
  title,
  mode = 'folder',
}: {
  diskId: number
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (relativePath: string) => void
  title: string
  mode?: 'folder' | 'file'
}) {
  const [path, setPath] = useState('')
  const [newFolderName, setNewFolderName] = useState('')
  const { data, isPending, isError } = useBrowseDisk(open ? diskId : null, path)
  const mkdir = useMkdir(diskId)

  const segments = path ? path.split('/') : []

  function goTo(index: number) {
    setPath(segments.slice(0, index + 1).join('/'))
  }

  function createFolder() {
    if (!newFolderName.trim()) return
    const target = path ? `${path}/${newFolderName}` : newFolderName
    mkdir.mutate(target, {
      onSuccess: () => {
        setNewFolderName('')
        setPath(target)
      },
      onError: (error) => toast.error(t('disks.createFolderFailed', { message: error.message })),
    })
  }

  function selectFile(name: string) {
    onSelect(path ? `${path}/${name}` : name)
    onOpenChange(false)
  }

  const entries = data?.entries ?? []
  const folders = entries.filter((e) => e.is_dir)
  const files = mode === 'file' ? entries.filter((e) => !e.is_dir) : []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {mode === 'file' ? t('disks.navigateToFile') : t('disks.navigateToFolder')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
          <button className="hover:underline" onClick={() => setPath('')}>
            /
          </button>
          {segments.map((segment, i) => (
            <span key={i} className="flex items-center gap-1">
              <span>/</span>
              <button className="hover:underline" onClick={() => goTo(i)}>
                {segment}
              </button>
            </span>
          ))}
        </div>

        <div className="max-h-64 overflow-auto rounded border">
          {isPending && <p className="p-3 text-sm text-muted-foreground">{t('common.loading')}</p>}
          {isError && <p className="p-3 text-sm text-destructive">{t('disks.cannotReadFolder')}</p>}
          {folders.map((entry) => (
            <button
              key={entry.name}
              className="flex w-full items-center gap-2 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted"
              onClick={() => setPath(path ? `${path}/${entry.name}` : entry.name)}
            >
              <FolderIcon className="size-4 text-muted-foreground" />
              {entry.name}
            </button>
          ))}
          {files.map((entry) => (
            <button
              key={entry.name}
              className="flex w-full items-center gap-2 border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted"
              onClick={() => selectFile(entry.name)}
            >
              <FileIcon className="size-4 text-muted-foreground" />
              {entry.name}
            </button>
          ))}
          {folders.length === 0 && files.length === 0 && (
            <p className="p-3 text-sm text-muted-foreground">{t('disks.emptyFolder')}</p>
          )}
        </div>

        {mode === 'folder' && (
          <>
            <div className="flex items-center gap-2">
              <Input
                placeholder={t('disks.newFolderNamePlaceholder')}
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
              />
              <Button variant="outline" size="icon" onClick={createFolder} disabled={mkdir.isPending}>
                <FolderPlusIcon className="size-4" />
              </Button>
            </div>

            <DialogFooter>
              <Button
                onClick={() => {
                  onSelect(path)
                  onOpenChange(false)
                }}
              >
                {t('disks.selectPath', { path: path || '/' })}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
