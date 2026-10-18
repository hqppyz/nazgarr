import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { RetryUploadButton } from '@/components/upload/RetryUploadButton'

const retry = vi.fn((_confirm: boolean) => Promise.resolve({}))
vi.mock('@/api/hooks/uploads', () => ({ useRetryUpload: () => ({ mutateAsync: retry, isPending: false }) }))

afterEach(() => {
  cleanup()
  retry.mockClear()
})

const target = (id: number, label: string, extra = {}) => ({
  id, tracker_label: label, action: 'upload', status: 'failed', torrent_id_remote: null, error_message: 'rejected',
  approved_name: 'Movie (2024) 1080p', ...extra,
})
const job = (targets: unknown[], status = 'partial') => ({ id: 3, status, targets }) as unknown as UploadJob

describe('RetryUploadButton', () => {
  it('lists the trackers that failed before publishing and sends them back to the queue', async () => {
    render(<RetryUploadButton job={job([
      target(1, 'ITT'),
      target(2, 'Done', { status: 'done', torrent_id_remote: '5', error_message: null }),
      target(3, 'NotSeeding', { status: 'done', torrent_id_remote: '6', error_message: 'seed_failed' }),
    ])} />)

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('ITT')).toBeTruthy()
    expect(within(dialog).queryByText('Done')).toBeNull()
    expect(within(dialog).queryByText('NotSeeding')).toBeNull() // per questo c'è "Riprova il seed"
    expect(within(dialog).queryByRole('alert')).toBeNull()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Retry' }))

    await vi.waitFor(() => expect(retry).toHaveBeenCalledWith(false))
  })

  it('asks to check the tracker first when the sending was interrupted', async () => {
    render(<RetryUploadButton job={job([target(1, 'ITT', { error_message: 'interrupted' })], 'failed')} />)

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('alert').textContent).toContain('ITT: the sending was interrupted')
    fireEvent.click(within(dialog).getByRole('button', { name: 'I checked: retry' }))

    await vi.waitFor(() => expect(retry).toHaveBeenCalledWith(true))
  })

  it('is not offered when nothing can be retried', () => {
    render(<RetryUploadButton job={job([target(1, 'ITT')], 'cancelled')} />)
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    cleanup()
    render(<RetryUploadButton job={job([target(1, 'ITT', { status: 'done', torrent_id_remote: '5', error_message: 'seed_failed' })])} />)
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
  })
})
