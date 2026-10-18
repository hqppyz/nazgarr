// I campi di configurazione che un adapter dichiara (GET /api/plugins):
// valori iniziali, corpo da inviare e campi obbligatori mancanti. Il form è
// src/components/AdapterConfigFields.tsx.

import type { Schemas } from '@/api/client'

export type ConfigField = Schemas['ConfigFieldResponse']
export type ConfigValues = Record<string, string | boolean>

// I valori iniziali dal salvato (o dai default del campo). I segreti partono
// sempre vuoti: non tornano mai dall'API.
export function initialConfigValues(fields: ConfigField[], saved: Record<string, unknown> | undefined): ConfigValues {
  return Object.fromEntries(
    fields.map((field) => {
      const value = field.type === 'secret' ? '' : (saved?.[field.key] ?? field.default)
      if (field.type === 'boolean') return [field.key, value === true]
      return [field.key, value == null ? '' : String(value)]
    }),
  )
}

// Quello da inviare: un segreto lasciato vuoto non si manda (resta com'era).
export function configPayload(fields: ConfigField[], values: ConfigValues): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const field of fields) {
    const value = values[field.key]
    if (field.type === 'secret' && value === '') continue
    out[field.key] = value
  }
  return out
}

export function missingRequired(fields: ConfigField[], values: ConfigValues, secretsSet: string[] = []) {
  return fields.some(
    (field) => field.required && field.type !== 'boolean' && values[field.key] === '' && !secretsSet.includes(field.key),
  )
}
