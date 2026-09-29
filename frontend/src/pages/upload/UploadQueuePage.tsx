import { PlusIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { useUploads } from '@/api/hooks/uploads'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { t } from '@/lib/i18n'

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  awaiting_match: 'outline',
  awaiting_decision: 'outline',
  done: 'default',
  partial: 'secondary',
  failed: 'destructive',
}

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
              <TableHead>File</TableHead>
              <TableHead>{t('upload.status')}</TableHead>
              <TableHead>Tracker</TableHead>
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
                <TableCell className="max-w-md truncate font-mono text-xs">{job.relative_path}</TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[job.status] ?? 'outline'}>{job.status}</Badge>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">{job.targets.map((target) => target.tracker_label).join(', ')}</TableCell>
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
