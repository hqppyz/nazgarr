import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { FileNamesCard } from '@/components/upload/FileNamesCard'
import { PackMixedCard } from '@/components/upload/PackMixedCard'

// Un salvataggio degli override rifiutato dal server (audit 2026-10-18,
// finding 58): la scelta tornava indietro senza dire perché.
const toastError = vi.hoisted(() => vi.fn())
vi.mock('sonner', () => ({ toast: { error: toastError, success: vi.fn() } }))
const updateOverrides = vi.fn()
vi.mock('@/api/hooks/uploads', () => ({
  useUpdateOverrides: () => ({ mutate: updateOverrides, isPending: false }),
}))

function failing() {
  updateOverrides.mockImplementation((_overrides, options?: { onError?: (error: Error) => void }) =>
    options?.onError?.(new Error('This API key is read only.')),
  )
}

const job = {
  id: 5, status: 'awaiting_decision', overrides: {},
  analysis: {
    pack_mixed: { group: ['GRP', 'OTHER'] },
    file_names: {
      available: ['generated', 'original'], default: 'generated',
      previews: {
        generated: { name: 'My.Show.S01.mkv', files: ['My.Show.S01.mkv'], count: 1 },
        original: { name: 'My Show S01.mkv', files: ['My Show S01.mkv'], count: 1 },
      },
    },
  },
} as unknown as UploadJob

describe('saving the overrides from the decision', () => {
  beforeEach(() => {
    toastError.mockClear()
    updateOverrides.mockReset()
  })

  it('says why the confirmation of a mixed pack was not saved', () => {
    failing()
    render(<PackMixedCard job={job} />)

    fireEvent.click(screen.getByRole('checkbox'))

    expect(updateOverrides.mock.lastCall?.[0]).toEqual({ pack_mixed_confirmed: true })
    expect(toastError).toHaveBeenCalledWith('This API key is read only.')
  })

  it('says why another way of naming the files was not saved', () => {
    failing()
    render(<FileNamesCard job={job} />)

    fireEvent.click(screen.getByRole('button', { name: 'Original' }))

    expect(updateOverrides.mock.lastCall?.[0]).toEqual({ file_naming: 'original' })
    expect(toastError).toHaveBeenCalledWith('This API key is read only.')
  })
})
