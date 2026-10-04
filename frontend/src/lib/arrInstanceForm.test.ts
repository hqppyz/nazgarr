import { describe, expect, it } from 'vitest'

import { arrConnectionBody, arrInstanceBody, emptyArrForm } from '@/lib/arrInstanceForm'

describe('arrInstanceBody', () => {
  const saved = { label: 'r', base_url: 'http://r', priority: 2, timeout_seconds: 30, basic_auth_username: 'u' }

  it('creates with basic auth only when it is turned on', () => {
    const form = { ...emptyArrForm(), label: 'r', baseUrl: 'http://r', apiKey: 'k' }
    expect(arrInstanceBody(form, false)).toEqual({
      label: 'r', base_url: 'http://r', priority: 0, timeout_seconds: 15, api_key: 'k',
      basic_auth_username: undefined, basic_auth_password: undefined,
    })
  })

  it('on edit keeps saved secrets and clears basic auth when it is turned off', () => {
    const form = emptyArrForm(saved)
    expect(arrInstanceBody(form, true)).toMatchObject({ api_key: undefined, basic_auth_username: 'u', basic_auth_password: undefined })
    expect(arrInstanceBody({ ...form, basicAuth: false }, true)).toMatchObject({ basic_auth_username: '' })
  })

  it('tests the connection with what is in the form', () => {
    expect(arrConnectionBody({ ...emptyArrForm(saved), apiKey: 'new' })).toEqual({
      base_url: 'http://r', api_key: 'new', timeout_seconds: 30, basic_auth_username: 'u', basic_auth_password: '',
    })
  })
})
