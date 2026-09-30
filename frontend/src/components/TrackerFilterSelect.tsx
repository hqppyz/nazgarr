import { FilterIcon } from 'lucide-react'

import { useSetSetting } from '@/api/hooks/settings'
import { useTrackers } from '@/api/hooks/trackers'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'
import { TRACKER_FILTER_SETTING, useTrackerFilter } from '@/lib/trackerFilter'
import { TrackerLogo } from '@/pages/config/ServiceIcons'

// In alto a destra su dashboard, libreria e torrent: lo stato del seeding
// per tutti i torrent, per i soli tracker configurati o per un tracker.
// La scelta si salva (impostazione tracker_filter) e resta quella di default.
export function TrackerFilterSelect() {
  const value = useTrackerFilter()
  const setValue = useSetSetting(TRACKER_FILTER_SETTING)
  const { data: trackers } = useTrackers()
  const enabled = (trackers ?? []).filter((tracker) => tracker.enabled)
  const labelOf = (v: string | null) => {
    if (v === 'configured') return t('trackerFilter.configured')
    const tracker = enabled.find((tr) => String(tr.id) === v)
    return tracker ? tracker.label : t('trackerFilter.all')
  }
  return (
    <Select value={value} onValueChange={(v) => v != null && setValue.mutate(v)}>
      <SelectTrigger size="sm" className="w-52" title={t('trackerFilter.help')}>
        <FilterIcon className="size-3.5 text-muted-foreground" />
        <SelectValue>{(v: string | null) => labelOf(v)}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{t('trackerFilter.all')}</SelectItem>
        <SelectItem value="configured">{t('trackerFilter.configured')}</SelectItem>
        {enabled.map((tracker) => (
          <SelectItem key={tracker.id} value={String(tracker.id)}>
            <span className="flex items-center gap-2 [&>div]:size-4">
              <TrackerLogo trackerId={tracker.id} />
              {tracker.label}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
