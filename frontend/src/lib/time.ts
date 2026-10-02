import { uiLocale } from '@/lib/i18n'

// "3 days ago" / "in 5 days", arrotondato all'unità più grande sensata:
// per ultima/prossima ricerca sul tracker nella scheda di dettaglio.
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['day', 86_400],
  ['hour', 3_600],
  ['minute', 60],
]

const formatter = new Intl.RelativeTimeFormat(uiLocale(), { numeric: 'auto' })

export function relativeFromNow(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '—'
  const seconds = Math.round((parseApiDate(iso).getTime() - now) / 1000)
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return formatter.format(Math.round(seconds / size), unit)
  }
  return formatter.format(0, 'minute')
}

// Le date che arrivano da SQLite non hanno fuso orario ("2026-09-24T09:00:00")
// ma il backend le salva sempre in UTC (datetime.now(UTC)): senza fuso vanno
// lette come UTC, non come ora locale — altrimenti in Italia ogni durata
// risultava sfasata di 1-2 ore (il cronometro della run partiva da 2:00:00).
const HAS_TIMEZONE = /(Z|[+-]\d{2}:?\d{2})$/

export function parseApiDate(value: string): Date {
  return new Date(HAS_TIMEZONE.test(value) ? value : `${value}Z`)
}
