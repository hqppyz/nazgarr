import { describe, expect, it, vi } from 'vitest'

import { isChunkLoadError, reloadOnce } from '@/lib/chunkReload'

function memory(): Pick<Storage, 'getItem' | 'setItem'> {
  const data = new Map<string, string>()
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) }
}

describe('reloadOnce', () => {
  it('reloads once, then leaves the error to the page instead of looping', () => {
    const storage = memory()
    const reload = vi.fn()
    expect(reloadOnce(storage, reload, 1_000_000)).toBe(true)
    expect(reloadOnce(storage, reload, 1_010_000)).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
    // Molto più tardi (un altro aggiornamento): di nuovo una ricarica.
    expect(reloadOnce(storage, reload, 1_000_000 + 5 * 60_000)).toBe(true)
    expect(reload).toHaveBeenCalledTimes(2)
  })

  it('does not reload without storage, where a loop could not be stopped', () => {
    const reload = vi.fn()
    const broken = { getItem: () => { throw new Error('denied') }, setItem: () => undefined }
    expect(reloadOnce(broken, reload)).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })
})

describe('isChunkLoadError', () => {
  it('recognises the messages of Chrome, Firefox and Safari', () => {
    expect(isChunkLoadError(new TypeError('Failed to fetch dynamically imported module: /assets/a.js'))).toBe(true)
    expect(isChunkLoadError(new TypeError('error loading dynamically imported module: /assets/a.js'))).toBe(true)
    expect(isChunkLoadError(new TypeError('Importing a module script failed.'))).toBe(true)
    expect(isChunkLoadError(new TypeError("Cannot read properties of undefined (reading 'x')"))).toBe(false)
  })
})
