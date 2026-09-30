import { ArrowLeftIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { UploadJob } from '@/api/hooks/uploads'
import { JobActions } from '@/components/upload/JobActions'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'

// In cima alla pagina, fuori dalle schede: indietro a sinistra, annulla ed
// elimina a destra.
export function JobToolbar({ job }: { job: UploadJob }) {
  const navigate = useNavigate()
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Button variant="ghost" size="sm" onClick={() => navigate('/upload')}>
        <ArrowLeftIcon className="size-4" />
        {t('upload.backToList')}
      </Button>
      <JobActions job={job} />
    </div>
  )
}
