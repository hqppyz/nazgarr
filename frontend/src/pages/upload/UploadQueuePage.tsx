import { PlusIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { useUploads } from '@/api/hooks/uploads'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { t } from '@/lib/i18n'

// Elenco semplice dei job: la coda e lo storico con i dettagli arrivano
// con l'ultimo step del flusso v2 (docs/ROADMAP.md Phase 9).
export function UploadQueuePage() {
  const { data, isPending } = useUploads()
  const navigate = useNavigate()

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Upload</CardTitle>
        <Button onClick={() => navigate('/upload/new')}>
          <PlusIcon className="size-4" />
          {t('upload.newUpload')}
        </Button>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('upload.columnContent')}</TableHead>
              <TableHead>{t('upload.columnStatus')}</TableHead>
              <TableHead>{t('upload.trackers')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending && (
              <TableRow>
                <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {data?.map((job) => (
              <TableRow key={job.id} className="cursor-pointer" onClick={() => navigate(`/upload/${job.id}`)}>
                <TableCell className="max-w-md">
                  <p className="truncate text-sm font-medium">
                    {job.title ? `${job.title}${job.year ? ` (${job.year})` : ''}` : t('upload.untitled')}
                  </p>
                  <p className="truncate font-mono text-xs text-muted-foreground">{job.relative_path}</p>
                </TableCell>
                <TableCell>
                  <UploadStatusBadge status={job.status} />
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {job.targets.map((target) => target.tracker_label).join(', ')}
                </TableCell>
              </TableRow>
            ))}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                  {t('upload.noUploadsYet')}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
