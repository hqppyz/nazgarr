import { useQuery } from '@tanstack/react-query'
import { TriangleAlertIcon } from 'lucide-react'

import { api, unwrap } from '@/api/client'
import { t } from '@/lib/i18n'

// Le preferenze del client che contano per Nazgarr, chieste al client
// stesso (GET /api/torrent-clients/{id}/warnings, sola lettura). Per ora una:
// Transmission che rinomina i file incompleti in "<nome>.part" già durante
// il recheck (rename-partial-files, decisione dell'utente del 2026-10-19).
// Un client che non risponde non mostra niente: lo dice "Prova connessione".
export function ClientWarnings({ clientId, enabled }: { clientId: number; enabled: boolean }) {
  const { data } = useQuery({
    queryKey: ['torrent-clients', clientId, 'warnings'],
    queryFn: () =>
      unwrap(
        api.GET('/api/torrent-clients/{torrent_client_id}/warnings', {
          params: { path: { torrent_client_id: clientId } },
        }),
      ),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  })
  if (!data?.warnings.length) return null
  return (
    <>
      {data.warnings.map((code) => (
        <p key={code} role="note" className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-300">
          <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{t(`torrentClients.warning.${code}`)}</span>
        </p>
      ))}
    </>
  )
}
