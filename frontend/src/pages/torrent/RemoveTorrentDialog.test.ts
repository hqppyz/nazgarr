import { describe, expect, it } from 'vitest'

import type { Schemas } from '@/api/client'
import { canRemove } from '@/pages/torrent/RemoveTorrentDialog'

type Torrent = Schemas['NotImportedItem']

const torrent = (warnings: Torrent['removal_warnings'], status = 'met') =>
  ({ seed_requirement: { status }, removal_warnings: warnings }) as Torrent

describe('canRemove', () => {
  // Quali avvisi bloccano lo dice il server (audit 2026-10-18): la UI non ne
  // tiene una copia sua da tenere allineata.
  it('follows the blocking flag the server sends', () => {
    expect(canRemove(torrent([]))).toBe(true)
    expect(canRemove(torrent([{ code: 'last_seeder', params: {}, blocking: false }]))).toBe(true)
    expect(canRemove(torrent([{ code: 'shared_files', params: {}, blocking: true }]))).toBe(false)
    // Un codice nuovo che il server dice bloccante blocca anche senza una riga qui.
    expect(canRemove(torrent([{ code: 'something_new', params: {}, blocking: true }]))).toBe(false)
  })

  it('needs the seed requirement met', () => {
    expect(canRemove(torrent([], 'not_met'))).toBe(false)
  })
})
