import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { UploadJob, UploadTarget } from '@/api/hooks/uploads'
import { TrackerCheckCard } from '@/components/upload/TrackerCheckCard'

const verify = vi.fn()
vi.mock('@/api/hooks/uploads', () => ({ useVerifyTarget: () => ({ mutate: verify, isPending: false }) }))

afterEach(cleanup)

const dupe = (id: string, verdict: string, extra = {}) => ({
  torrent_id_remote: id, name: `Release.${id}`, size_bytes: 1e9, verdict, reasons: [], verification: null, ...extra,
})

const target = {
  id: 3, tracker_label: 'ITT', status: 'awaiting_decision', suggested_action: 'reseed', error_message: null,
  dupes: [
    dupe('1', 'identical'),
    dupe('2', 'same_slot', { reasons: ['covered_by_pack'] }),
    dupe('3', 'different', { reasons: ['resolution'] }),
  ],
} as unknown as UploadTarget
const job = { id: 9, status: 'awaiting_decision', targets: [target] } as unknown as UploadJob

describe('TrackerCheckCard', () => {
  it('shows each result with its verdict and runs the full hash check on the identical one', () => {
    render(<TrackerCheckCard job={job} target={target} />)

    expect(screen.getByText('Identical')).toBeTruthy()
    expect(screen.getByText('Dupe')).toBeTruthy()
    expect(screen.getByText('season pack that includes it')).toBeTruthy()
    expect(screen.getByText('other resolution')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Full hash check' }))
    expect(verify).toHaveBeenCalledWith({ targetId: 3, torrentIdRemote: '1' }, expect.anything())
  })

  it('shows a passed check instead of the button', () => {
    const verified = {
      ...target,
      dupes: [dupe('1', 'identical', { verification: { status: 'passed', reason: null, ok: 40, pieces: 40 } })],
    } as unknown as UploadTarget
    render(<TrackerCheckCard job={job} target={verified} />)

    expect(screen.getByText('Every piece matches (40): reseed instead of uploading.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Full hash check' })).toBeNull()
  })

  it("warns when no audio track is in the tracker's language", () => {
    const withLanguage = {
      ...job,
      analysis: { languages: { '7': { language: 'it', status: 'missing' } } },
    } as unknown as UploadJob
    render(<TrackerCheckCard job={withLanguage} target={{ ...target, tracker_id: 7 } as UploadTarget} />)
    expect(screen.getByText(/No audio track in Italian/)).toBeTruthy()
    cleanup()

    const fine = { ...job, analysis: { languages: { '7': { language: 'it', status: 'present' } } } } as unknown as UploadJob
    render(<TrackerCheckCard job={fine} target={{ ...target, tracker_id: 7 } as UploadTarget} />)
    expect(screen.queryByText(/audio track/)).toBeNull()
  })
})
