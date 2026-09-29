import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NamingRulesEditor, type NamingRules } from '@/components/NamingRulesEditor'

vi.mock('@/api/hooks/trackers', () => ({
  useNamingPreview: () => ({
    isError: false,
    data: {
      sample: { kind: 'example', label: null },
      variables: { resolution: '2160p' },
      names: { REMUX: 'Dune 2024 2160p-GRP' },
    },
  }),
}))

afterEach(cleanup)

let latest: NamingRules = {}

function Harness({ initial }: { initial: NamingRules }) {
  const [rules, setRules] = useState(initial)
  latest = rules
  return <NamingRulesEditor trackerId={1} value={rules} onChange={setRules} />
}

describe('NamingRulesEditor', () => {
  it('inserts a variable into the focused template and shows the preview under it', () => {
    render(<Harness initial={{ templates: { REMUX: '{title} {year}' } }} />)

    expect(screen.getByText('→ Dune 2024 2160p-GRP')).toBeTruthy()
    const remux = screen.getByLabelText('REMUX') as HTMLInputElement
    fireEvent.focus(remux)
    remux.setSelectionRange(remux.value.length, remux.value.length)
    fireEvent.click(screen.getByRole('button', { name: '{resolution}' }))

    expect(latest.templates).toEqual({ REMUX: '{title} {year} {resolution}' })
    expect(screen.getByRole('button', { name: '{resolution}' }).getAttribute('title')).toBe('2160p')
  })

  it('removes an emptied template so the default is used', () => {
    render(<Harness initial={{ templates: { default: '{title}', REMUX: '{title} REMUX' } }} />)

    fireEvent.change(screen.getByLabelText('REMUX'), { target: { value: '' } })

    expect(latest.templates).toEqual({ default: '{title}' })
  })
})
