import { CheckCircle2Icon, PencilIcon, PlusIcon, TrashIcon, XCircleIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { useAvailableMounts, useCreateDisk, useDeleteDisk, useDisks, useUpdateDisk, useVerifyDisk } from '@/api/hooks/disks'
import type { Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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

function VerifyButton({ diskId }: { diskId: number }) {
  const verify = useVerifyDisk()
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      data-tour="storage.verify"
      title={t('disks.verifyHardlink')}
      onClick={() =>
        verify.mutate(diskId, {
          onSuccess: (result) => {
            if (result.consistent) toast.success(t('disks.diskConsistent'))
            else toast.warning(result.warning ?? t('disks.diskInconsistent'))
          },
          onError: (error) => toast.error(t('disks.verificationFailed', { message: error.message })),
        })
      }
    >
      {verify.data?.consistent === false ? (
        <XCircleIcon className="size-4 text-destructive" />
      ) : (
        <CheckCircle2Icon className="size-4" />
      )}
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
  field: 'media_rel_path' | 'torrents_rel_path' | 'new_torrent_rel_path' | 'upload_rel_path'
  title: string
  emptyLabel?: string
}) {
  const [browserOpen, setBrowserOpen] = useState(false)
  const updateDisk = useUpdateDisk()

  return (
    <>
      <button
        className="font-mono text-xs text-muted-foreground hover:underline"
        data-tour={tour}
        data-tour-filled={value ? 'true' : undefined}
        onClick={() => setBrowserOpen(true)}
      >
        {value || emptyLabel || t('disks.setPath')}
      </button>
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

function EditDiskDialog({ disk }: { disk: Disk }) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState(disk.label)
  const [newTorrentRelPath, setNewTorrentRelPath] = useState(disk.new_torrent_rel_path ?? '')
  const updateDisk = useUpdateDisk()

  function submit() {
    updateDisk.mutate(
      {
        diskId: disk.id,
        body: {
          label,
          new_torrent_rel_path: newTorrentRelPath || undefined,
        },
      },
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
          <div className="grid gap-1.5">
            <Label htmlFor="disk-edit-new-torrent-rel-path">{t('disks.newHardlinkFolderLabel')}</Label>
            <Input
              id="disk-edit-new-torrent-rel-path"
              value={newTorrentRelPath}
              onChange={(e) => setNewTorrentRelPath(e.target.value)}
              placeholder="torrents/new"
            />
            <p className="text-xs text-muted-foreground">{t('disks.newHardlinkFolderHelp')}</p>
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

export function DisksSection() {
  const { data: disks, isPending } = useDisks()
  const deleteDisk = useDeleteDisk()

  return (
    <Card data-tour="storage.card">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Disks</CardTitle>
        <AddDiskDialog />
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('disks.label')}</TableHead>
              <TableHead>root_path</TableHead>
              <TableHead>{t('disks.mediaFolder')}</TableHead>
              <TableHead>{t('disks.seedingFolder')}</TableHead>
              <TableHead>{t('disks.newHardlinkFolderColumn')}</TableHead>
              <TableHead>{t('disks.uploadFolderColumn')}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-sm text-muted-foreground">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {disks?.map((disk) => (
              <TableRow key={disk.id} data-tour="storage.row">
                <TableCell className="font-medium">{disk.label}</TableCell>
                <TableCell className="font-mono text-xs">{disk.root_path}</TableCell>
                <TableCell>
                  <RelPathCell diskId={disk.id} value={disk.media_rel_path} field="media_rel_path" title={t('disks.mediaFolder')} tour="storage.media-folder" />
                </TableCell>
                <TableCell>
                  <RelPathCell
                    diskId={disk.id}
                    value={disk.torrents_rel_path}
                    field="torrents_rel_path"
                    title={t('disks.seedingFolderDialogTitle')}
                    tour="storage.seeding-folder"
                  />
                </TableCell>
                <TableCell>
                  {/* Dove l'executor crea i NUOVI hardlink (season pack e film
                      ricreati): vuoto = la cartella di seeding stessa. */}
                  <RelPathCell
                    diskId={disk.id}
                    value={disk.new_torrent_rel_path}
                    field="new_torrent_rel_path"
                    title={t('disks.newHardlinkFolderLabel')}
                    tour="storage.new-folder"
                    emptyLabel={t('disks.sameAsSeedingFolder')}
                  />
                </TableCell>
                <TableCell>
                  {/* Dove il flusso di upload crea gli hardlink e fa seedare
                      i torrent: vuoto = la cartella di seeding. */}
                  <RelPathCell
                    diskId={disk.id}
                    value={disk.upload_rel_path}
                    field="upload_rel_path"
                    title={t('disks.uploadFolderLabel')}
                    tour="storage.upload-folder"
                    emptyLabel={t('disks.sameAsSeedingFolder')}
                  />
                </TableCell>
                <TableCell className="flex justify-end gap-1">
                  <VerifyButton diskId={disk.id} />
                  <EditDiskDialog disk={disk} />
                  <Button variant="ghost" size="icon-sm" title={t('common.delete')} onClick={() => deleteDisk.mutate(disk.id)}>
                    <TrashIcon className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {disks?.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-sm text-muted-foreground">
                  {t('disks.noDisksConfigured')}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
