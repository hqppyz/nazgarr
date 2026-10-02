import { describe, expect, it } from 'vitest'

import { en } from '@/locales/en'
import { check, stepsFor, TOURS, type Condition } from '@/onboarding/tours'

// Il sorgente di ogni componente: un'ancora citata da un tour deve esistere
// davvero (data-tour="…" o tour="…"), se no un refactor rompe il tour in silenzio.
const sources = import.meta.glob('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const anchors = new Set(
  Object.entries(sources)
    .filter(([path]) => !path.includes('.test.'))
    .flatMap(([, code]) => [...code.matchAll(/\b(?:data-tour|tour)="([^"]+)"/g)].map((m) => m[1])),
)

const conditionAnchor = (c: Condition | undefined) =>
  !c ? undefined : 'element' in c ? c.element : 'gone' in c ? c.gone : 'filled' in c ? c.filled : undefined

describe('tours', () => {
  it.each(TOURS.map((tour) => [tour.key, tour]))('%s: every anchor exists, every step has its texts', (_key, tour) => {
    const ids = tour.steps.map((s) => s.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const step of tour.steps) {
      for (const anchor of [step.anchor, conditionAnchor(step.waitFor), conditionAnchor(step.skipIf)]) {
        if (anchor) expect(anchors, `${tour.key}.${step.id}: ${anchor}`).toContain(anchor)
      }
      const base = `onboarding.tour.${tour.key}.${step.id}`
      expect(en, base).toHaveProperty(`${base}.title`)
      expect(en, base).toHaveProperty(`${base}.body`)
      if (step.skipTo) expect(ids).toContain(step.skipTo)
      if (step.backTo) expect(ids).toContain(step.backTo)
      // Un passo senza Next deve avere qualcosa che lo fa avanzare.
      if (!step.next) expect(step.waitFor, `${tour.key}.${step.id}`).toBeDefined()
    }
  })

  it('leaves out the steps the welcome answers do not ask for', () => {
    const storage = TOURS.find((t) => t.key === 'storage')!
    expect(stepsFor(storage, { upload: false, arr: false }).map((s) => s.id)).not.toContain('upload')
    expect(stepsFor(storage, { upload: true, arr: false }).map((s) => s.id)).toContain('upload')
  })

  it('checks conditions on the page and on the configuration', () => {
    document.body.innerHTML = '<div data-tour="a"></div><button data-tour="b" data-tour-filled="true"></button>'
    expect(check({ element: 'a' }, document, undefined)).toBe(true)
    expect(check({ gone: 'a' }, document, undefined)).toBe(false)
    expect(check({ filled: 'b' }, document, undefined)).toBe(true)
    expect(check({ filled: 'a' }, document, undefined)).toBe(false)
    expect(check({ status: 'metadata' }, document, { metadata: { done: true } })).toBe(true)
    expect(check({ status: 'metadata' }, document, undefined)).toBe(false)
  })
})
