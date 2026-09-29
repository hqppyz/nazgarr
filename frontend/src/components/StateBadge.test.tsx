import { render, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StateBadge } from '@/components/StateBadge'

describe('StateBadge', () => {
  it.each([
    ['seeding', 'seeding'],
    ['orphan_media', 'orphaned'],
    ['orphan_torrent', 'orphaned'],
    ['ignored', 'not imported'],
    ['unmatched', 'unmatched'],
  ])('renders the label for state %s', (state, expectedLabel) => {
    const { container } = render(<StateBadge state={state} />)
    expect(within(container).getByText(expectedLabel)).toBeInTheDocument()
  })

  it('falls back to the raw state string for an unknown state', () => {
    const { container } = render(<StateBadge state="something_new" />)
    expect(within(container).getByText('something new')).toBeInTheDocument()
  })

  it('shows seeding in green, never in the theme primary colour', () => {
    const { container } = render(<StateBadge state="seeding" />)
    expect(within(container).getByText('seeding').className).toContain('emerald')
  })
})

describe('compact StateBadge (tree rows)', () => {
  it('keeps the state colour and uses the xxs mono size', () => {
    const { container } = render(<StateBadge state="seeding" compact />)
    const cls = within(container).getByText('seeding').className
    expect(cls).toContain('text-emerald-700')
    expect(cls).toContain('text-[length:var(--text-xxs)]')
    expect(cls).toContain('font-mono')
    expect(cls).not.toMatch(/(^|\s)text-xs(\s|$)/)
  })
})
