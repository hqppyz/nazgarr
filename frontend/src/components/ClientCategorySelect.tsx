import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

const NONE = '__none__'

// Una categoria del client, scelta solo fra quelle che il client ha. Una
// salvata che il client non ha più resta visibile, segnata, finché non la si
// cambia.
export function ClientCategorySelect({
  categories,
  value,
  onChange,
  noneLabel,
  className,
  id,
}: {
  categories: string[]
  value: string | null
  onChange: (category: string | null) => void
  noneLabel?: string
  className?: string
  id?: string
}) {
  const missing = value !== null && !categories.includes(value)
  const options = [
    { value: NONE, label: noneLabel ?? t('torrentClients.noCategory') },
    ...(missing ? [{ value, label: t('torrentClients.categoryMissing', { category: value }) }] : []),
    ...categories.map((category) => ({ value: category, label: category })),
  ]
  return (
    <Select value={value ?? NONE} onValueChange={(v) => onChange(v === NONE || v == null ? null : v)}>
      <SelectTrigger id={id} size="sm" className={cn('w-full max-w-44', className)}>
        <SelectValue>{(v: string | null) => options.find((o) => o.value === v)?.label ?? options[0].label}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
