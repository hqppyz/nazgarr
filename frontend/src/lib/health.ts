import type { Schemas } from '@/api/client'
import { t } from '@/lib/i18n'
import { parseApiDate } from '@/lib/time'

type HistoryPoint = Schemas['HistoryPoint']

// Fasce di salute: etichetta e colore, usati da anello e grafico così il
// colore dice subito come sta la libreria. color = variabile del tema Tailwind.
export function healthLabel(value: number): { label: string; dot: string; color: string } {
  if (value >= 90) return { label: t('dashboard.healthGreat'), dot: 'bg-emerald-500', color: 'var(--color-emerald-500)' }
  if (value >= 75) return { label: t('dashboard.healthGood'), dot: 'bg-sky-500', color: 'var(--color-sky-500)' }
  if (value >= 50) return { label: t('dashboard.healthFair'), dot: 'bg-amber-500', color: 'var(--color-amber-500)' }
  return { label: t('dashboard.healthPoor'), dot: 'bg-red-500', color: 'var(--color-red-500)' }
}

// Un punto per giorno (giorno locale): se in un giorno ci sono più scansioni
// vale l'ultima. x = mezzanotte di quel giorno, per un asse del tempo vero.
export function dailyHealth(history: HistoryPoint[]): { day: number; health: number }[] {
  const byDay = new Map<number, { at: number; health: number }>()
  for (const point of history) {
    // Senza libreria (solo torrent e upload) una scansione non ha salute.
    if (!point.finished_at || point.health_snapshot == null) continue
    const at = parseApiDate(point.finished_at)
    const day = new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime()
    const current = byDay.get(day)
    if (!current || at.getTime() > current.at) byDay.set(day, { at: at.getTime(), health: point.health_snapshot })
  }
  return [...byDay.entries()].sort(([a], [b]) => a - b).map(([day, v]) => ({ day, health: v.health }))
}
