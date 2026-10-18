// Nome e stato delle istanze (questa e le altre Nazgarr collegate), per lo
// switcher, la pagina Istanze e il blocco di un'istanza remota.

import { useInstances, type Instance } from '@/api/hooks/instances'
import { t } from '@/lib/i18n'

// Il pallino di stato di un'istanza: verde connessa e compatibile, giallo
// connessa con un avviso, rosso non raggiungibile o bloccata.
export function instanceDot(instance: Instance | null): string {
  const status = instance?.status
  if (!instance) return 'bg-emerald-500'
  if (!status) return 'bg-muted-foreground'
  if (status.status !== 'ok' || status.compatibility.startsWith('block')) return 'bg-red-500'
  if (status.compatibility !== 'ok') return 'bg-amber-500'
  return 'bg-emerald-500'
}

export function useLocalName(): string {
  const { data } = useInstances(true)
  return data?.local_name || t('instances.thisInstance')
}
