import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { OneTimeSecretDialog } from '@/components/OneTimeSecretDialog'

const copyText = vi.hoisted(() => vi.fn(async () => true))
vi.mock('@/lib/clipboard', () => ({ copyText }))
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

// Il segreto che Nazgarr mostra una volta sola (una API key, il segreto di un
// webhook): si vede, si copia, e chiudere lo dimentica.
describe('OneTimeSecretDialog', () => {
  it('shows nothing without a secret', () => {
    render(<OneTimeSecretDialog secret={null} title="Your new API key" description="Copy it now" onClose={vi.fn()} />)
    expect(screen.queryByText('Your new API key')).toBeNull()
  })

  it('shows the secret once, copies exactly it, and closes with Done', async () => {
    const onClose = vi.fn()
    render(
      <OneTimeSecretDialog secret="nzg_SECRET123" title="Your new API key" description="Copy it now" onClose={onClose}>
        <p>extra hint</p>
      </OneTimeSecretDialog>,
    )
    expect(screen.getByText('Your new API key')).toBeTruthy()
    expect(screen.getByText('nzg_SECRET123')).toBeTruthy()
    expect(screen.getByText('extra hint')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    await vi.waitFor(() => expect(copyText).toHaveBeenCalledWith('nzg_SECRET123', expect.anything()))
    expect(toast.error).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('says to copy it by hand when the clipboard refuses', async () => {
    copyText.mockResolvedValueOnce(false)
    render(<OneTimeSecretDialog secret="nzg_SECRET123" title="Key" description="Copy it now" onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith('Copy failed: select the key and copy it by hand.'))
  })
})
