import { describe, expect, it } from 'vitest'

import { configPayload, initialConfigValues, missingRequired, type ConfigField } from '@/components/AdapterConfigFields'

const fields: ConfigField[] = [
  { key: 'url', label: 'URL', type: 'url', required: true, choices: [] },
  { key: 'password', label: 'Password', type: 'secret', required: true, choices: [] },
  { key: 'port', label: 'Port', type: 'number', required: false, default: 58846, choices: [] },
  { key: 'ssl', label: 'SSL', type: 'boolean', required: false, default: false, choices: [] },
]

describe('adapter config fields', () => {
  it('starts from the saved values, secrets always empty', () => {
    expect(initialConfigValues(fields, { url: 'http://d', port: 1 })).toEqual({ url: 'http://d', password: '', port: '1', ssl: false })
    expect(initialConfigValues(fields, undefined).port).toBe('58846')
  })

  it('never sends a secret left empty, so it stays as it was', () => {
    const values = { url: 'http://d', password: '', port: '1', ssl: true }
    expect(configPayload(fields, values)).toEqual({ url: 'http://d', port: '1', ssl: true })
    // Obbligatorio ma già impostato sul server: va bene anche vuoto.
    expect(missingRequired(fields, values)).toBe(true)
    expect(missingRequired(fields, values, ['password'])).toBe(false)
  })
})
