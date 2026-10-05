import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GettingStartedCard } from '@/onboarding/GettingStartedCard'
import { DEFAULT_STATE, parseState, type OnboardingState } from '@/onboarding/state'
import { isDone, visibleSteps } from '@/onboarding/steps'
import { WelcomeDialog } from '@/onboarding/WelcomeDialog'

const save = vi.fn()
let current: OnboardingState | null = null
let steps: Record<string, { done: boolean }> = {}

vi.mock('@/onboarding/state', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/onboarding/state')>()
  return {
    ...actual,
    useOnboarding: () => ({ isPending: false, state: current, save, saving: false }),
    useSetupStatus: () => ({ data: { steps, required: [], optional: [], complete: false } }),
  }
})

const status = (done: string[]) =>
  Object.fromEntries(
    ['storage', 'clients', 'metadata', 'arr', 'trackers', 'upload', 'first_scan'].map((k) => [k, { done: done.includes(k) }]),
  )

beforeEach(() => {
  save.mockReset()
  current = null
  steps = status([])
})
afterEach(cleanup)

describe('onboarding state', () => {
  it('reads what was saved and ignores anything else', () => {
    expect(parseState(null)).toBeNull()
    expect(parseState('nope')).toBeNull()
    expect(parseState('{"status":"weird"}')).toBeNull()
    expect(parseState('{"status":"dismissed"}')).toEqual({ ...DEFAULT_STATE, status: 'dismissed' })
  })

  it('shows only the steps the welcome answers ask for, the seen ones count as done', () => {
    const state = { ...DEFAULT_STATE, answers: { upload: false, arr: false }, seen: ['exclusions'] }
    const keys = visibleSteps(state).map((s) => s.key)
    expect(keys).not.toContain('upload')
    expect(keys).not.toContain('arr')
    const exclusions = visibleSteps(state).find((s) => s.key === 'exclusions')!
    expect(isDone(exclusions, undefined, state)).toBe(true)
  })
})

describe('WelcomeDialog', () => {
  it('opens on a fresh instance and saves the answers', () => {
    render(<WelcomeDialog />)

    fireEvent.click(screen.getByRole('button', { name: 'Start the setup' }))

    expect(save).toHaveBeenCalledWith({ ...DEFAULT_STATE, status: 'active' })
  })

  it('stays closed once a disk exists or the tour was already seen', () => {
    steps = status(['storage'])
    render(<WelcomeDialog />)
    expect(screen.queryByText('Welcome to Nazgarr')).toBeNull()
    cleanup()

    steps = status([])
    current = { ...DEFAULT_STATE, status: 'dismissed' }
    render(<WelcomeDialog />)
    expect(screen.queryByText('Welcome to Nazgarr')).toBeNull()
  })
})

describe('GettingStartedCard', () => {
  it('counts what the configuration already has and links each step to its screen', () => {
    current = DEFAULT_STATE
    steps = status(['storage', 'clients'])
    render(<MemoryRouter><GettingStartedCard /></MemoryRouter>)

    expect(screen.getByText('Getting started')).toBeTruthy()
    expect(screen.getByText('2/9')).toBeTruthy() // upload sì, Radarr/Sonarr no; con "Il resto di Nazgarr"
    expect(screen.getByText('Trackers').closest('a')?.getAttribute('href')).toBe('/config?tab=trackers')
  })

  it('offers to finish once every required step is done', () => {
    current = DEFAULT_STATE
    steps = status(['storage', 'clients', 'metadata', 'trackers', 'first_scan'])
    render(<MemoryRouter><GettingStartedCard /></MemoryRouter>)

    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(save).toHaveBeenCalledWith({ ...DEFAULT_STATE, status: 'done' })
  })

  it('is hidden when the tour is not active', () => {
    current = { ...DEFAULT_STATE, status: 'dismissed' }
    render(<MemoryRouter><GettingStartedCard /></MemoryRouter>)
    expect(screen.queryByText('Getting started')).toBeNull()
  })
})
