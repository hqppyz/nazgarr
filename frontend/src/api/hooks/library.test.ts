import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { isOtherLibraryQuery } from '@/api/hooks/library'

describe('isOtherLibraryQuery', () => {
  it('refreshes the other library views after a removal, not the list the answer already holds', async () => {
    const client = new QueryClient()
    client.setQueryData(['library', 'not-imported'], { torrents: [] })
    client.setQueryData(['library', 'items', 'all'], [])

    await client.invalidateQueries({ queryKey: ['library'], predicate: isOtherLibraryQuery })

    expect(client.getQueryState(['library', 'not-imported'])?.isInvalidated).toBe(false)
    expect(client.getQueryState(['library', 'items', 'all'])?.isInvalidated).toBe(true)
  })
})
