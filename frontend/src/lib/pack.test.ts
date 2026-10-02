import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { packProblem, packUploadTarget, readPackState, usePackSelection } from '@/lib/pack'

describe('pack of episodes picked by hand', () => {
  it('needs two videos on one disk', () => {
    expect(packProblem([{ diskId: 1, path: 'a.mkv' }])).toBe('tooFew')
    expect(packProblem([{ diskId: 1, path: 'a.mkv' }, { diskId: 2, path: 'b.mkv' }])).toBe('manyDisks')
    expect(packProblem([{ diskId: 1, path: 'a.mkv' }, { diskId: 1, path: 'b.mkv' }])).toBeNull()
  })

  it('travels to the new upload in the navigation state, not the URL', () => {
    const target = packUploadTarget([{ diskId: 3, path: 'torrents/E01/e01.mkv' }, { diskId: 3, path: 'torrents/E02/e02.mkv' }], 'tv/1399')
    expect(target.to).toBe('/upload/new?tmdb=tv%2F1399')
    expect(readPackState(target.state)).toEqual({ diskId: 3, files: ['torrents/E01/e01.mkv', 'torrents/E02/e02.mkv'] })
    expect(readPackState(null)).toBeNull()
    expect(readPackState({ pack: { diskId: 3, files: [] } })).toBeNull()
  })

  it('picks a whole run with SHIFT, in the order shown', () => {
    const videos = ['e1', 'e2', 'e3', 'e4', 'e5'].map((path) => ({ diskId: 1, path }))
    const { result } = renderHook(() => usePackSelection())
    act(() => result.current.pick(videos[1], false, videos))
    act(() => result.current.pick(videos[3], true, videos))
    expect(result.current.files.map((f) => f.path)).toEqual(['e2', 'e3', 'e4'])
    // SHIFT su un video già scelto: l'intervallo si toglie.
    act(() => result.current.pick(videos[2], true, videos))
    expect(result.current.files.map((f) => f.path)).toEqual(['e2'])
  })
})
