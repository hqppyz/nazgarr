import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { ResultStep } from '@/components/upload/ResultStep'

describe('ResultStep', () => {
  it('shows each tracker outcome, the tracker link and why one failed', () => {
    const job = {
      status: 'partial',
      targets: [
        { id: 1, tracker_label: 'ITT', action: 'upload', status: 'done', approved_name: 'Movie (2024)',
          remote_url: 'https://itt/torrents/5', error_message: 'seed_failed' },
        { id: 2, tracker_label: 'Other', action: 'upload', status: 'failed', approved_name: 'Movie (2024)',
          remote_url: null, error_message: 'rejected' },
      ],
      events: [
        { id: 1, target_id: 2, level: 'error', code: 'upload_failed', params: { error: 'rejected: dupe' }, created_at: '' },
      ],
    } as unknown as UploadJob

    render(
      <QueryClientProvider client={new QueryClient()}>
        <ResultStep job={job} />
      </QueryClientProvider>,
    )

    expect(screen.getByText('Partly done: some trackers failed')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Open on the tracker/ }).getAttribute('href')).toBe('https://itt/torrents/5')
    expect(screen.getByText(/adding it to the client failed/)).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /Retry seeding/ })).toHaveLength(1) // solo dove il seed è fallito
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy() // il tracker fallito si riprova
    expect(screen.getByText('Upload failed: rejected: dupe')).toBeTruthy()
  })

  it('offers retry seeding after a failed recheck, also of a reseed, and shows a pending recheck as a warning', () => {
    const job = {
      status: 'done',
      targets: [
        { id: 1, tracker_label: 'ITT', action: 'reseed', status: 'done', approved_name: 'Movie (2024)',
          remote_url: null, error_message: 'seed_recheck_failed' },
        { id: 2, tracker_label: 'Other', action: 'reseed', status: 'done', approved_name: 'Movie (2024)',
          remote_url: null, error_message: 'seed_recheck_pending' },
      ],
      events: [],
    } as unknown as UploadJob

    render(
      <QueryClientProvider client={new QueryClient()}>
        <ResultStep job={job} />
      </QueryClientProvider>,
    )

    // L'etichetta del tracker anche negli step dell'esecuzione: la card è quella col bordo.
    const card = (label: string) => screen.getByText(label, { selector: 'div.border span' }).closest('div.border') as HTMLElement
    expect(within(card('ITT')).getByRole('button', { name: /Retry seeding/ })).toBeTruthy()
    expect(within(card('ITT')).getByText(/recheck failed: the torrent stays stopped/)).toBeTruthy()
    // In attesa del recheck: un avviso tradotto, nessun pulsante (Nazgarr lo avvia da sé).
    expect(within(card('Other')).queryByRole('button', { name: /Retry seeding/ })).toBeNull()
    const pending = within(card('Other')).getByText(/stopped until its recheck passes/)
    expect(pending.className).toContain('text-amber-600')
    expect(screen.queryByText('seed_recheck_pending')).toBeNull()
  })
})
