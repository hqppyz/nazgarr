import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { api, unwrap } from '@/api/client'
import { t } from '@/lib/i18n'

const STORAGE_KEY = 'nazgarr-upload-notice'
const POLL_MS = 15_000

function lastSeen(): number | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value ? Number(value) : null
  } catch {
    return null
  }
}

function remember(id: number) {
  try {
    localStorage.setItem(STORAGE_KEY, String(id))
  } catch {
    // niente da ricordare: al prossimo caricamento si riparte da ora
  }
}

// Gli avvisi delle release della cartella osservata (nazgarr/upload_watch.py),
// ovunque tu sia nell'app: rilevata, e pronta per la tua decisione. Il
// pulsante porta all'upload. L'ultimo visto resta nel browser: niente doppioni
// e, aprendo l'app, niente arretrati (la coda degli upload li mostra già).
export function UploadNotices() {
  const navigate = useNavigate()
  const [after, setAfter] = useState<number | null>(lastSeen)
  const shown = useRef(new Set<number>())
  const { data } = useQuery({
    queryKey: ['uploads', 'notices', after],
    queryFn: () => unwrap(api.GET('/api/uploads/notices', { params: { query: after == null ? {} : { after } } })),
    refetchInterval: POLL_MS,
  })

  useEffect(() => {
    if (!data) return
    for (const notice of data.notices) {
      if (shown.current.has(notice.id)) continue
      shown.current.add(notice.id)
      const name = notice.title ? `${notice.title}${notice.year ? ` (${notice.year})` : ''}` : notice.path
      toast(t(`upload.notice.${notice.kind}`), {
        description: name,
        duration: notice.kind === 'ready' ? 20_000 : 8_000,
        action: { label: t('upload.notice.open'), onClick: () => navigate(`/upload/${notice.upload_id}`) },
      })
    }
    if (data.latest_id !== after) {
      remember(data.latest_id)
      setAfter(data.latest_id)
    }
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  return null
}
