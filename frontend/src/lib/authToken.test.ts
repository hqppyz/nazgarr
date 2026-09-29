import { beforeEach, describe, expect, it } from 'vitest'

import { getToken } from '@/lib/authToken'

describe('getToken', () => {
  beforeEach(() => localStorage.clear())

  it('moves a token saved under the old project name, so nobody is logged out by the rename', () => {
    localStorage.setItem('gauntletarr_token', 'jwt')

    expect(getToken()).toBe('jwt')
    expect(localStorage.getItem('nazgarr_token')).toBe('jwt')
    expect(localStorage.getItem('gauntletarr_token')).toBeNull()
  })
})
