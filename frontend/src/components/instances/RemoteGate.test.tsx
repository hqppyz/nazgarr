import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Instance } from '@/api/hooks/instances'
import { RemoteGate } from '@/components/instances/RemoteGate'

let instance: Instance

vi.mock('@/api/hooks/instances', () => ({
  useInstances: () => ({ data: { instances: [instance], local_version: '0.9.0' }, isPending: false }),
}))

function remote(status: string, compatibility = 'ok'): Instance {
  return {
    id: 3,
    label: 'Office',
    base_url: 'https://office.example',
    status: { status, error: null, version: '0.9.0', level: 'write', compatibility },
  } as Instance
}

describe('RemoteGate', () => {
  beforeEach(() => localStorage.setItem('nazgarr-instance', '3'))

  it('shows the views of a compatible instance', () => {
    instance = remote('ok')
    render(<RemoteGate><p>its views</p></RemoteGate>)
    expect(screen.getByText('its views')).toBeTruthy()
  })

  it('blocks the views of an instance that refuses the key, with a way back', () => {
    instance = remote('bad_key')
    render(<RemoteGate><p>its views</p></RemoteGate>)
    expect(screen.queryByText('its views')).toBeNull()
    expect(screen.getByText(/refuses the API key/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Back to this instance' })).toBeTruthy()
  })

  it('blocks a newer instance', () => {
    instance = remote('ok', 'block_newer')
    render(<RemoteGate><p>its views</p></RemoteGate>)
    expect(screen.queryByText('its views')).toBeNull()
    expect(screen.getByText(/Newer than this one/)).toBeTruthy()
  })
})
