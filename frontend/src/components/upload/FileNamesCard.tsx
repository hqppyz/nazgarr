import { CheckIcon, FileVideoIcon, FolderIcon, PencilIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useUpdateOverrides, type UploadJob } from '@/api/hooks/uploads'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { t } from '@/lib/i18n'
import { fileNames, fileNamingMode } from '@/lib/upload'

// L'estensione di un file solo resta la sua: si scrive il resto del nome.
function splitExtension(name: string, isFolder: boolean): [string, string] {
  const dot = name.lastIndexOf('.')
  return isFolder || dot <= 0 ? [name, ''] : [name.slice(0, dot), name.slice(dot)]
}

// I nomi dei file dentro il torrent di un upload (nazgarr/upload/file_names.py):
// quelli del torrent in hardlink su un client, generati dal pattern di
// Settings > Upload, o quelli della sorgente. Uno per job: il torrent è lo
// stesso per tutti i tracker. Il nome generato (il file, o la cartella di un
// pack) si può riscrivere a mano: override content_name.
export function FileNamesCard({ job }: { job: UploadJob }) {
  const save = useUpdateOverrides(job.id)
  const [editing, setEditing] = useState<string | null>(null)
  const names = fileNames(job)
  const mode = fileNamingMode(job)
  if (!names || !mode) return null
  const preview = names.previews[mode]
  // Il default per primo, senza etichetta: è quello che si usa se non si sceglie.
  const modes = [...names.available].sort((a, b) => Number(b === names.default) - Number(a === names.default))
  const isFolder = preview?.files.some((f) => f.includes('/'))
  const written = typeof job.overrides.content_name === 'string' ? job.overrides.content_name : null
  const editable = mode === 'generated' && job.status === 'awaiting_decision'
  const [stem, extension] = splitExtension(preview?.name ?? '', Boolean(isFolder))

  const saveName = (value: string | null) => {
    const rest = Object.fromEntries(Object.entries(job.overrides).filter(([key]) => key !== 'content_name'))
    save.mutate(value ? { ...rest, file_naming: 'generated', content_name: value } : rest, {
      onSuccess: () => setEditing(null),
      onError: (error) => toast.error(error.message),
    })
  }

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="text-base">{t('upload.fileNames.title')}</CardTitle>
        <CardDescription>{t('upload.fileNames.description')}</CardDescription>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-3">
        <ToggleGroupSingle
          value={mode}
          variant="outline"
          size="sm"
          className="w-full flex-wrap gap-1.5"
          disabled={save.isPending || job.status !== 'awaiting_decision'}
          onValueChange={(value) => value && save.mutate({ ...job.overrides, file_naming: value })}
        >
          {modes.map((m) => (
            <ToggleGroupItem key={m} value={m} className="flex-none rounded-md px-3 whitespace-nowrap">
              {t(`upload.fileNames.mode.${m}`)}
            </ToggleGroupItem>
          ))}
        </ToggleGroupSingle>
        {preview && (
          <div className="grid min-w-0 gap-1 rounded-md border bg-muted/30 p-2.5 font-mono text-xs">
            {editing !== null ? (
              <form
                className="flex min-w-0 items-center gap-1.5"
                onSubmit={(e) => {
                  e.preventDefault()
                  saveName(editing.trim() || null)
                }}
              >
                {isFolder ? <FolderIcon className="size-3.5 shrink-0" /> : <FileVideoIcon className="size-3.5 shrink-0" />}
                <Input
                  autoFocus
                  aria-label={t('upload.fileNames.nameLabel')}
                  className="h-7 min-w-0 flex-1 px-2 font-mono text-xs pointer-coarse:h-9"
                  value={editing}
                  onChange={(e) => setEditing(e.target.value)}
                  onKeyDown={(e) => e.key === 'Escape' && setEditing(null)}
                />
                {extension && <span className="shrink-0 text-muted-foreground">{extension}</span>}
                <Button type="submit" size="icon-sm" variant="ghost" disabled={save.isPending} aria-label={t('upload.fileNames.saveName')}>
                  <CheckIcon />
                </Button>
                <Button type="button" size="icon-sm" variant="ghost" onClick={() => setEditing(null)} aria-label={t('upload.fileNames.cancelName')}>
                  <XIcon />
                </Button>
              </form>
            ) : (
              <span className="flex min-w-0 items-center gap-1.5 font-medium">
                {isFolder ? <FolderIcon className="size-3.5 shrink-0" /> : <FileVideoIcon className="size-3.5 shrink-0" />}
                <span className="min-w-0 break-all">{preview.name}</span>
                {editable && (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    className="ml-auto shrink-0"
                    onClick={() => setEditing(stem)}
                    aria-label={t('upload.fileNames.editName')}
                    title={t('upload.fileNames.editName')}
                  >
                    <PencilIcon />
                  </Button>
                )}
              </span>
            )}
            {isFolder &&
              preview.files.map((file) => (
                <span key={file} className="pl-5 break-all text-muted-foreground">
                  {file.slice(file.indexOf('/') + 1)}
                </span>
              ))}
            {preview.single_file && (
              <span className="pl-5 break-all text-muted-foreground">
                {preview.folder ? t('upload.fileNames.seedsInFolder', { folder: preview.folder }) : t('upload.fileNames.seedsWithoutFolder')}
              </span>
            )}
            {preview.count > preview.files.length && (
              <span className="pl-5 text-muted-foreground">
                {t('upload.fileNames.more', { count: preview.count - preview.files.length })}
              </span>
            )}
          </div>
        )}
        {mode === 'generated' && written && (
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <span>{t(isFolder ? 'upload.fileNames.writtenFolder' : 'upload.fileNames.writtenFile')}</span>
            {editable && (
              <button type="button" className="font-medium underline" disabled={save.isPending} onClick={() => saveName(null)}>
                {t('upload.fileNames.restoreName')}
              </button>
            )}
          </p>
        )}
        <p className="text-xs text-muted-foreground">{t(`upload.fileNames.help.${mode}`)}</p>
      </CardContent>
    </Card>
  )
}
