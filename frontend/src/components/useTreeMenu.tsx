import { EyeOffIcon, UploadIcon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useExcludeFile } from '@/api/hooks/library'
import { filesUnder, type TreeFileEntry, type TreeNode, type TreeRowActions } from '@/components/FileTree'
import type { RowMenuItem } from '@/components/RowContextMenu'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { t } from '@/lib/i18n'
import { newUploadLink } from '@/lib/upload'

interface Pending {
  path: string
  isDir: boolean
  count: number
}

// Il menu contestuale delle viste ad albero (Media files e Torrent files),
// sempre presente su file e cartelle:
// - upload / reseed, attivo solo per i file orfani di quella vista
//   (orphanState), altrimenti visibile ma spento con il perché;
// - escludi il file o l'intera cartella, dopo una conferma (nessun file
//   viene toccato: si aggiunge un pattern a Configuration > Exclusions).
export function useTreeMenu(orphanState: string): { actions: TreeRowActions; dialog: React.ReactNode } {
  const navigate = useNavigate()
  const exclude = useExcludeFile()
  const [pending, setPending] = useState<Pending | null>(null)
  const isOrphan = (file: TreeFileEntry) => file.state === orphanState && !file.excluded

  function fileReason(file: TreeFileEntry): string | null {
    if (file.excluded) return t('library.menu.reasonExcluded')
    if (file.disk_id == null) return t('library.menu.reasonNoDisk')
    if (file.state === 'seeding') return t('library.menu.reasonSeeding')
    if (file.state === 'ignored') return t('library.menu.reasonInClient')
    return isOrphan(file) ? null : t('library.menu.reasonNotOrphan')
  }

  function uploadItem(reason: string | null, to: () => string): RowMenuItem {
    return {
      label: t('itemDetail.uploadOrReseed'),
      icon: <UploadIcon />,
      disabled: reason !== null,
      hint: reason ?? undefined,
      onSelect: () => navigate(to()),
    }
  }

  const actions: TreeRowActions = {
    file: (file) => [
      uploadItem(fileReason(file), () =>
        newUploadLink({ diskId: file.disk_id as number, path: file.relative_path, isDir: false }),
      ),
      {
        label: t('library.menu.excludeFile'),
        icon: <EyeOffIcon />,
        disabled: file.excluded,
        hint: file.excluded ? t('library.menu.alreadyExcluded') : undefined,
        onSelect: () => setPending({ path: file.relative_path, isDir: false, count: 1 }),
      },
    ],
    folder: (node: TreeNode) => {
      const files = filesUnder(node)
      const disks = new Set(files.map((f) => f.disk_id))
      const reason = !files.some(isOrphan)
        ? t('library.menu.reasonNoOrphans')
        : disks.size !== 1 || files[0].disk_id == null
          ? t('library.menu.reasonManyDisks')
          : null
      const allExcluded = files.every((f) => f.excluded)
      return [
        uploadItem(reason, () => newUploadLink({ diskId: files[0].disk_id as number, path: node.path, isDir: true })),
        {
          label: t('library.menu.excludeFolder'),
          icon: <EyeOffIcon />,
          disabled: allExcluded,
          hint: allExcluded ? t('library.menu.alreadyExcluded') : undefined,
          onSelect: () => setPending({ path: node.path, isDir: true, count: files.length }),
        },
      ]
    },
  }

  const dialog = (
    <Dialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {pending?.isDir ? t('library.menu.excludeFolderTitle') : t('library.menu.excludeFileTitle')}
          </DialogTitle>
          <DialogDescription>
            {pending?.isDir
              ? t('library.menu.excludeFolderDescription', { count: pending.count })
              : t('library.menu.excludeFileDescription')}
          </DialogDescription>
        </DialogHeader>
        <p className="rounded-md bg-muted px-3 py-2 font-mono text-xs break-all">{pending?.path}</p>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setPending(null)}>
            {t('common.cancel')}
          </Button>
          <Button
            disabled={exclude.isPending}
            onClick={() =>
              pending &&
              exclude
                .mutateAsync({ relativePath: pending.path, isDir: pending.isDir })
                .then(() => setPending(null))
                .catch(() => {})
            }
          >
            {t('library.menu.excludeConfirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )

  return { actions, dialog }
}
