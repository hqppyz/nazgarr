import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NamingRulesEditor, type NamingRules } from '@/components/NamingRulesEditor'

vi.mock('@/api/hooks/trackers', () => ({
  useNamingPreview: () => ({
    isError: false,
    data: {
      sample: { kind: 'job', label: 'A.Very.Long.Release.Name.2024.2160p.UHD.BluRay.REMUX-GRP' },
      variables: { resolution: '2160p' },
      names: { default: 'Dune 2024 2160p-GRP' },
    },
  }),
}))

afterEach(cleanup)

function Harness({ initial, onChange }: { initial: NamingRules; onChange: (rules: NamingRules) => void }) {
  const [rules, setRules] = useState(initial)
  return (
    <NamingRulesEditor
      trackerId={1}
      value={rules}
      onChange={(next) => {
        setRules(next)
        onChange(next)
      }}
    />
  )
}

const lastRules = (spy: ReturnType<typeof vi.fn>) => spy.mock.calls.at(-1)![0] as NamingRules

describe('NamingRulesEditor', () => {
  it('has one main pattern, inserts variables at the cursor and previews the name', () => {
    const onChange = vi.fn()
    render(<Harness initial={{ templates: { default: '{title} {year}' } }} onChange={onChange} />)

    expect(screen.getByText('→ Dune 2024 2160p-GRP')).toBeTruthy()
    expect(screen.queryByLabelText('Pattern for REMUX')).toBeNull()
    const main = screen.getByLabelText('Release name pattern') as HTMLInputElement
    fireEvent.focus(main)
    main.setSelectionRange(main.value.length, main.value.length)
    fireEvent.click(screen.getByRole('button', { name: '{resolution}' }))

    expect(lastRules(onChange).templates).toEqual({ default: '{title} {year} {resolution}' })
    expect(screen.getByRole('button', { name: '{resolution}' }).getAttribute('title')).toBe('2160p')
  })

  it('shows a type pattern only when there is one, and removes it', () => {
    const onChange = vi.fn()
    render(<Harness initial={{ templates: { default: '{title}', REMUX: '{title} REMUX' } }} onChange={onChange} />)

    expect(screen.getByLabelText('Pattern for REMUX')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))

    expect(lastRules(onChange).templates).toEqual({ default: '{title}' })
  })

  it('keeps type labels as a value format', () => {
    const onChange = vi.fn()
    render(<Harness initial={{ templates: { default: '{title} {type}' } }} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('REMUX'), { target: { value: '{source} REMUX VU' } })

    expect(lastRules(onChange).type_labels).toEqual({ REMUX: '{source} REMUX VU' })
  })
})
