import { describe, expect, it } from 'vitest'

import { FULL_CHECK_MAX_ERRORS, fullCheckRefetchInterval } from './fullChecks'

describe('fullCheckRefetchInterval', () => {
  it('polls every second while the check is queued or running', () => {
    expect(fullCheckRefetchInterval(undefined, false, 0)).toBe(1000)
    expect(fullCheckRefetchInterval('running', false, 0)).toBe(1000)
    expect(fullCheckRefetchInterval('done', false, 0)).toBe(false)
  })

  it('backs off on errors and then stops instead of polling forever', () => {
    expect(fullCheckRefetchInterval(undefined, true, 1)).toBe(5000)
    expect(fullCheckRefetchInterval(undefined, true, FULL_CHECK_MAX_ERRORS)).toBe(false)
  })
})
