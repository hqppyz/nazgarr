import { describe, expect, it as test } from 'vitest'

import { en } from '@/locales/en'
import { it } from '@/locales/it'

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

describe('the Italian locale', () => {
  test('has every English key and nothing else', () => {
    const english = Object.keys(en).sort()
    const italian = Object.keys(it).sort()
    expect(italian.filter((key) => !(key in en))).toEqual([])
    expect(english.filter((key) => !(key in it))).toEqual([])
  })

  test('keeps the same placeholders in every translation', () => {
    const mismatched = Object.entries(en)
      .filter(([key, text]) => JSON.stringify(placeholders(text)) !== JSON.stringify(placeholders(it[key as keyof typeof it] ?? '')))
      .map(([key]) => key)
    expect(mismatched).toEqual([])
  })

  test('is actually translated, not a copy of the English', () => {
    // Molte etichette restano uguali (Torrent, Upload, Dashboard...): ma se
    // più della metà fosse identica, qualcosa non è stato tradotto.
    const same = Object.entries(en).filter(([key, text]) => it[key as keyof typeof it] === text).length
    expect(same / Object.keys(en).length).toBeLessThan(0.5)
  })
})
