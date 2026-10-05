import { describe, expect, it } from 'vitest'

import { torrentClientPayload, type TorrentClientForm } from '@/lib/torrentClientForm'

const form = (overrides: Partial<TorrentClientForm>): TorrentClientForm => ({
  label: 'c', adapterType: 'qbittorrent', baseUrl: 'http://c', username: 'u', password: '', apiToken: 'k', quiInstanceId: '3',
  ...overrides,
})

describe('torrentClientPayload', () => {
  it('sends only the credentials that client type uses', () => {
    expect(torrentClientPayload(form({ password: 'p' }))).toMatchObject({ username: 'u', password: 'p', api_token: undefined })
    expect(torrentClientPayload(form({ adapterType: 'deluge', password: 'p' }))).toMatchObject({ username: undefined, password: 'p' })
    expect(torrentClientPayload(form({ adapterType: 'qui' }))).toMatchObject({
      username: undefined, password: undefined, api_token: 'k', qui_instance_id: 3,
    })
  })

  it('never sends an empty secret, which on edit means keep the saved one', () => {
    expect(torrentClientPayload(form({ password: '' })).password).toBeUndefined()
  })

  it('sends only label, address and fields for a plugin client', () => {
    expect(torrentClientPayload(form({ adapterType: 'x' }), { token: 't' })).toEqual({
      label: 'c', base_url: 'http://c', config: { token: 't' },
    })
  })
})
