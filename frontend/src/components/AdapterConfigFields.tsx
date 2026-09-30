import type { Schemas } from '@/api/client'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { t } from '@/lib/i18n'

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

// Il form dei campi che un adapter di un plugin dichiara (GET /api/plugins).
export function AdapterConfigFields({
  fields,
  values,
  onChange,
  secretsSet = [],
  idPrefix,
}: {
  fields: ConfigField[]
  values: ConfigValues
  onChange: (values: ConfigValues) => void
  secretsSet?: string[]
  idPrefix: string
}) {
  const set = (key: string, value: string | boolean) => onChange({ ...values, [key]: value })
  return (
    <>
      {fields.map((field) => {
        const id = `${idPrefix}-${field.key}`
        const label = `${field.label}${field.required ? ' *' : ''}`
        if (field.type === 'boolean') {
          return (
            <div key={field.key} className="flex items-center gap-2">
              <Switch id={id} checked={values[field.key] === true} onCheckedChange={(checked) => set(field.key, checked)} />
              <Label htmlFor={id}>{field.label}</Label>
              {field.help && <span className="text-xs text-muted-foreground">{field.help}</span>}
            </div>
          )
        }
        return (
          <div key={field.key} className="grid gap-1.5">
            <Label htmlFor={id}>{label}</Label>
            {field.type === 'choice' ? (
              <Select value={String(values[field.key] ?? '')} onValueChange={(v) => v != null && set(field.key, v)}>
                <SelectTrigger id={id}>
                  <SelectValue>{(v: string | null) => v || t('common.choose')}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {field.choices.map((choice) => (
                    <SelectItem key={choice} value={choice}>
                      {choice}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                id={id}
                type={field.type === 'secret' ? 'password' : field.type === 'number' ? 'number' : 'text'}
                value={String(values[field.key] ?? '')}
                placeholder={field.type === 'secret' && secretsSet.includes(field.key) ? t('torrentClients.leaveEmptyToKeep') : undefined}
                onChange={(e) => set(field.key, e.target.value)}
              />
            )}
            {field.help && <p className="text-xs text-muted-foreground">{field.help}</p>}
          </div>
        )
      })}
    </>
  )
}
