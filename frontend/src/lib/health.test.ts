import { describe, expect, it } from 'vitest'

import { dailyHealth, healthLabel } from '@/lib/health'

const point = (finished_at: string, health_snapshot: number) => ({
  run_id: 1, run_type: 'manual', finished_at, health_snapshot, items_scanned: 0, matches_found: 0,
  auto_executed: 0, pending_review: 0, errors: 0,
})

describe('dailyHealth', () => {
  it('keeps one point per day, the last scan of that day, in time order', () => {
    const days = dailyHealth([
      point('2026-09-29T20:00:00', 91),
      point('2026-09-29T08:00:00', 80),
      point('2026-09-27T12:00:00', 70),
    ])
    expect(days.map((d) => d.health)).toEqual([70, 91])
    expect(new Date(days[1].day).getDate()).toBe(29)
  })
})

describe('healthLabel', () => {
  it('colors by health band', () => {
    expect(healthLabel(95).color).toContain('emerald')
    expect(healthLabel(80).color).toContain('sky')
    expect(healthLabel(60).color).toContain('amber')
    expect(healthLabel(20).color).toContain('red')
  })
})
