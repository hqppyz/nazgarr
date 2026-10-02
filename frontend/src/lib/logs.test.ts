import { describe, expect, it } from 'vitest'

import { shortLogger } from '@/lib/logs'

describe('shortLogger', () => {
  it('names the libraries and drops the app prefix', () => {
    expect(shortLogger('apscheduler.executors.default')).toBe('scheduler')
    expect(shortLogger('uvicorn.access')).toBe('http')
    expect(shortLogger('uvicorn.error')).toBe('server')
    expect(shortLogger('nazgarr.pipeline')).toBe('pipeline')
    expect(shortLogger('app.pipeline')).toBe('pipeline') // log di prima del rinomino
    expect(shortLogger('app.adapters.tracker.unit3d')).toBe('tracker.unit3d')
    expect(shortLogger('httpx')).toBe('httpx')
  })
})
