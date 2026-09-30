import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RowContextMenu } from '@/components/RowContextMenu'

afterEach(cleanup)

describe('RowContextMenu', () => {
  it('opens on right click and runs the chosen action', async () => {
    const onSelect = vi.fn()
    render(
      <RowContextMenu title="torrents/Movie.mkv" items={[{ label: 'Upload / reseed', onSelect }]}>
        <div>row</div>
      </RowContextMenu>,
    )

    fireEvent.contextMenu(screen.getByText('row'))
    fireEvent.click(await screen.findByText('Upload / reseed'))

    expect(onSelect).toHaveBeenCalled()
    expect(screen.queryByText('torrents/Movie.mkv')).toBeNull()
  })

  it('adds nothing without items', () => {
    const { container } = render(
      <RowContextMenu items={[]}>
        <div>row</div>
      </RowContextMenu>,
    )
    expect(container.innerHTML).toBe('<div>row</div>')
  })
})
