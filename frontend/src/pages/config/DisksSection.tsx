import { FolderIcon, HardDriveIcon, InfoIcon, PencilIcon, PlusIcon, TrashIcon, XIcon, ZapIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import {
  useAddDiskFolder,
  useAvailableMounts,
  useCreateDisk,
  useDeleteDisk,
  useDisks,
  useRemoveDiskFolder,
  useUpdateDisk,
  useVerifyDisk,
} from '@/api/hooks/disks'
import type { Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
import { SettingsHeader } from '@/components/SettingsHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'
import { DiskBrowserDialog } from '@/pages/config/DiskBrowserDialog'
import { autosaveFeedback } from '@/lib/autosave'

type Disk = Schemas['DiskResponse']

function AddDiskDialog() {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [rootPath, setRootPath] = useState('')
  const { data: mounts } = useAvailableMounts()
  const createDisk = useCreateDisk()

  // Precompila root_path con disk_scan_root (il mount unico, caso comune,
  // es. /data) così il campo non parte vuoto — resta comunque modificabile.
  useEffect(() => {
    if (mounts?.scan_root && rootPath === '') setRootPath(mounts.scan_root)
  }, [mounts?.scan_root]) // eslint-disable-line react-hooks/exhaustive-deps

  function submit() {
    createDisk.mutate(
      { label, root_path: rootPath },
      {
        onSuccess: () => {
          setOpen(false)
          setLabel('')
          setRootPath('')
        },
        onError: (error) => toast.error(t('disks.createDiskFailed', { message: error.message })),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button data-tour="storage.add"><PlusIcon className="size-4" />{t('disks.addDisk')}</Button>} />
      <DialogContent data-tour="storage.dialog">
        <DialogHeader>
          <DialogTitle>{t('disks.addDisk')}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5" data-tour="storage.dialog.label">
            <Label htmlFor="disk-label">{t('disks.label')}</Label>
            <Input id="disk-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="main" />
          </div>
          <div className="grid gap-1.5" data-tour="storage.dialog.root">
            <Label htmlFor="disk-root-path">root_path</Label>
            <Input
              id="disk-root-path"
              value={rootPath}
              onChange={(e) => setRootPath(e.target.value)}
              placeholder="/data/disk1"
            />
            <p className="text-xs text-muted-foreground">{t('disks.rootPathHelp')}</p>
          </div>
          {mounts?.mounts.length ? (
            <div className="grid gap-1.5">
              <Label>{t('disks.chooseSubfolder')}</Label>
              <Select value={rootPath} onValueChange={setRootPath}>
                <SelectTrigger>
                  <SelectValue placeholder={t('disks.subfolderPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {mounts.mounts.map((m) => (
                    <SelectItem key={m} value={m}>
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">{t('disks.multiDiskHelp')}</p>
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button data-tour="storage.dialog.create" onClick={submit} disabled={!label || !rootPath || createDisk.isPending}>
            {t('disks.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// La prova del disco (nazgarr/library/disk_folders.py test_disk): cartelle, filesystem e
// un hardlink di prova fra le cartelle, come "Prova connessione" dei client.
// st_dev cambiato da solo è un avviso: su FUSE cambia a ogni rimontaggio.
function DiskTestButton({ diskId }: { diskId: number }) {
  const verify = useVerifyDisk()
  return (
    <Button
      variant="outline"
      size="sm"
      data-tour="storage.verify"
      title={t('disks.testHelp')}
      disabled={verify.isPending}
      onClick={() =>
        verify.mutate(diskId, {
          onSuccess: (result) => {
            const checks = result.checks ?? []
            const links = checks.filter((c) => c.code === 'hardlink_ok').length
            // st_dev cambiato: aggiornato se gli hardlink funzionano, se no lasciato com'era.
            const key = (c: (typeof checks)[number]) =>
              c.code === 'st_dev_changed' && !(c.params as { updated?: boolean }).updated ? 'st_dev_changed_kept' : c.code
            const notes = checks
              .filter((c) => c.level !== 'ok')
              .map((c) => t(`disks.check.${key(c)}`, c.params as Record<string, string | number>))
            const description = notes.length ? (
              <ul className="grid gap-1">{notes.map((note) => <li key={note}>{note}</li>)}</ul>
            ) : undefined
            if (!result.consistent) toast.error(t('disks.testFailed'), { description, duration: 15000 })
            else if (notes.length) toast.warning(t('disks.testPassedWithNotes', { count: links }), { description, duration: 10000 })
            else toast.success(t('disks.testPassed', { count: links }))
          },
          onError: (error) => toast.error(t('disks.verificationFailed', { message: error.message })),
        })
      }
    >
      <ZapIcon className="size-4" />
      {t('disks.test')}
    </Button>
  )
}

function RelPathCell({
  diskId,
  value,
  field,
  title,
  emptyLabel,
  tour,
}: {
  tour?: string
  diskId: number
  value: string | null
  field: 'new_torrent_rel_path' | 'upload_rel_path' | 'watch_rel_path'
  title: string
  emptyLabel?: string
}) {
  const [browserOpen, setBrowserOpen] = useState(false)
  const updateDisk = useUpdateDisk()

  return (
    <>
      <span className="inline-flex items-center gap-1">
        <button
          className="font-mono text-xs text-muted-foreground hover:underline"
          data-tour={tour}
          data-tour-filled={value ? 'true' : undefined}
          onClick={() => setBrowserOpen(true)}
        >
          {value || emptyLabel || t('disks.setPath')}
        </button>
        {/* Le cartelle facoltative (con un "vuoto" che vuol dire qualcosa) si possono togliere. */}
        {value && emptyLabel && (
          <button
            className="text-muted-foreground hover:text-foreground"
            title={t('disks.clearPath')}
            aria-label={t('disks.clearPath')}
            onClick={() => updateDisk.mutate({ diskId, body: { [field]: '' } }, autosaveFeedback(title))}
          >
            <XIcon className="size-3" />
          </button>
        )}
      </span>
      <DiskBrowserDialog
        diskId={diskId}
        open={browserOpen}
        onOpenChange={setBrowserOpen}
        title={title}
        onSelect={(path) => updateDisk.mutate({ diskId, body: { [field]: path } }, autosaveFeedback(title))}
      />
    </>
  )
}

// Modifica del disco: solo l'etichetta (root_path non cambia, le cartelle
// si gestiscono sulla scheda).
function EditDiskDialog({ disk }: { disk: Disk }) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState(disk.label)
  const updateDisk = useUpdateDisk()

  function submit() {
    updateDisk.mutate(
      { diskId: disk.id, body: { label } },
      {
        onSuccess: () => setOpen(false),
        onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="ghost" size="icon-sm" title={t('common.edit')}><PencilIcon className="size-4" /></Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('disks.editDisk')}</DialogTitle>
          <DialogDescription>{t('disks.rootPathNotEditable')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="disk-edit-label">{t('disks.label')}</Label>
            <Input id="disk-edit-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label>root_path</Label>
            <Input value={disk.root_path} disabled />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!label || updateDisk.isPending}>
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Le cartelle media o di seeding di un disco, più di una (nazgarr/library/disk_folders.py):
// ognuna si toglie con la sua X (sul disco non cambia niente), "Aggiungi"
// apre il selettore. Il backend rifiuta quelle che si sovrappongono o stanno
// su un altro filesystem, con il motivo.
function FolderList({
  disk,
  kind,
  title,
  help,
  empty,
  tour,
}: {
  disk: Disk
  kind: 'media' | 'seeding'
  title: string
  help: string
  empty: string
  tour: string
}) {
  const [browserOpen, setBrowserOpen] = useState(false)
  const add = useAddDiskFolder()
  const remove = useRemoveDiskFolder()
  const folders = (disk.folders ?? []).filter((f) => f.kind === kind)
  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium" title={help}>{title}</span>
        <Button
          variant="ghost"
          size="xs"
          data-tour={tour}
          data-tour-filled={folders.length > 0 ? 'true' : undefined}
          onClick={() => setBrowserOpen(true)}
        >
          <PlusIcon className="size-3.5" />
          {t('disks.addFolder')}
        </Button>
      </div>
      {folders.length === 0 ? (
        <p className="rounded-md border border-dashed px-2.5 py-1.5 text-xs text-muted-foreground">{empty}</p>
      ) : (
        <ul className="grid gap-1">
          {folders.map((folder) => (
            <li key={`${folder.kind}:${folder.relative_path}`} className="flex min-w-0 items-center gap-2 rounded-md border bg-muted/30 px-2.5 py-1">
              <FolderIcon className="size-3.5 shrink-0 text-primary" />
              <span className="min-w-0 flex-1 truncate font-mono text-xs" title={folder.relative_path}>
                {folder.relative_path}
              </span>
              {folder.id != null && (
                <button
                  className="text-muted-foreground hover:text-foreground"
                  title={t('disks.removeFolder')}
                  aria-label={t('disks.removeFolder')}
                  disabled={remove.isPending}
                  onClick={() =>
                    remove.mutate({ diskId: disk.id, folderId: folder.id as number }, autosaveFeedback(title))
                  }
                >
                  <XIcon className="size-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <DiskBrowserDialog
        diskId={disk.id}
        open={browserOpen}
        onOpenChange={setBrowserOpen}
        title={title}
        onSelect={(path) =>
          add.mutate(
            { diskId: disk.id, kind, path },
            { onError: (error) => toast.error(t('disks.addFolderFailed', { message: error.message })), onSuccess: () => toast.success(t('disks.folderAdded', { path })) },
          )
        }
      />
    </div>
  )
}

export function DisksSection() {
  const { data: disks, isPending } = useDisks()
  const deleteDisk = useDeleteDisk()

  return (
    <div className="grid content-start gap-4">
      <div data-tour="storage.card">
        <SettingsHeader title={t('config.tabStorage')} description={t('config.descStorage')} action={<AddDiskDialog />} />
      </div>
      {isPending && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {disks?.length === 0 && (
        <Card>
          <CardContent className="py-6 text-center text-sm text-muted-foreground">{t('disks.noDisksConfigured')}</CardContent>
        </Card>
      )}
      {/* Senza nessuna cartella media il reseed non trova nulla: oggi riconosce
          solo i file della libreria (riconoscere i file in seed è un passo futuro). */}
      {disks && disks.length > 0 && disks.every((disk) => disk.media_folders.length === 0) && (
        <div className="flex gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
          <InfoIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <div className="grid gap-1">
            <p className="font-medium">{t('disks.noLibraryTitle')}</p>
            <p className="text-muted-foreground">{t('disks.noLibrary')}</p>
          </div>
        </div>
      )}
      {/* Una scheda per disco, come client e tracker: le sue cartelle media e
          di seeding (più di una), poi quelle per i nuovi hardlink, gli upload
          e le release. */}
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {disks?.map((disk) => (
          <Card key={disk.id} data-tour="storage.row" className="min-w-0">
            <CardHeader className="flex flex-row items-center gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                <HardDriveIcon className="size-4.5 text-muted-foreground" />
              </span>
              <div className="grid min-w-0 flex-1 gap-0.5">
                <CardTitle className="truncate text-base">{disk.label}</CardTitle>
                <span className="truncate font-mono text-xs text-muted-foreground" title={disk.root_path}>
                  {disk.root_path}
                </span>
              </div>
            </CardHeader>
            <CardContent className="grid min-w-0 gap-4 text-sm">
              <FolderList
                disk={disk}
                kind="seeding"
                title={t('disks.seedingFolders')}
                help={t('disks.seedingFoldersHelp')}
                empty={t('disks.noSeedingFolder')}
                tour="storage.seeding-folder"
              />
              <FolderList
                disk={disk}
                kind="media"
                title={t('disks.mediaFolders')}
                help={t('disks.mediaFoldersHelp')}
                empty={t('disks.noMediaFolder')}
                tour="storage.media-folder"
              />
              <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1.5 text-xs">
                <span className="text-muted-foreground" title={t('disks.newHardlinkFolderHelp')}>
                  {t('disks.newHardlinkFolderColumn')}
                </span>
                {/* Dove l'executor crea i NUOVI hardlink: vuoto = la prima cartella di seeding. */}
                <RelPathCell
                  diskId={disk.id}
                  value={disk.new_torrent_rel_path}
                  field="new_torrent_rel_path"
                  title={t('disks.newHardlinkFolderLabel')}
                  tour="storage.new-folder"
                  emptyLabel={t('disks.sameAsSeedingFolder')}
                />
                <span className="text-muted-foreground">{t('disks.uploadFolderColumn')}</span>
                {/* Dove il flusso di upload crea gli hardlink: vuoto = la prima cartella di seeding. */}
                <RelPathCell
                  diskId={disk.id}
                  value={disk.upload_rel_path}
                  field="upload_rel_path"
                  title={t('disks.uploadFolderLabel')}
                  tour="storage.upload-folder"
                  emptyLabel={t('disks.sameAsSeedingFolder')}
                />
                <span className="text-muted-foreground" title={t('disks.watchFolderHelp')}>
                  {t('disks.watchFolderColumn')}
                </span>
                {/* Le release nuove qui dentro partono da sole fino alla decisione (nazgarr/upload/watch.py). */}
                <RelPathCell
                  diskId={disk.id}
                  value={disk.watch_rel_path ?? null}
                  field="watch_rel_path"
                  title={t('disks.watchFolderLabel')}
                  tour="storage.watch-folder"
                  emptyLabel={t('disks.notWatched')}
                />
              </div>
              <div className="flex items-center gap-1 border-t pt-3">
                <DiskTestButton diskId={disk.id} />
                <span className="flex-1" />
                <EditDiskDialog disk={disk} />
                <Button variant="ghost" size="icon-sm" title={t('common.delete')} onClick={() => deleteDisk.mutate(disk.id)}>
                  <TrashIcon className="size-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
