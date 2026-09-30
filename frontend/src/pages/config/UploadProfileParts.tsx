import { CheckIcon, PlusIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-3">
      <h3 className="border-b pb-1 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}

const COMMON_FREELEECH = [25, 50, 75, 100]

// Le percentuali di freeleech che il tracker lascia scegliere a chi carica
// (campo UNIT3D "free") e quella preselezionata negli upload. Nessuna
// attiva = il tracker non lo concede.
export function FreeleechField({
  options,
  defaultValue,
  onChange,
}: {
  options: number[]
  defaultValue: number
  onChange: (body: { freeleech_options?: number[]; default_freeleech?: number }) => void
}) {
  const [custom, setCustom] = useState('')
  const all = [...new Set([...COMMON_FREELEECH, ...options])].sort((a, b) => a - b)
  const customValue = Number(custom)
  const canAdd = customValue > 0 && customValue <= 100 && !all.includes(customValue)

  const toggle = (value: number) => {
    const on = options.includes(value)
    onChange({
      freeleech_options: on ? options.filter((v) => v !== value) : [...options, value],
      ...(on && defaultValue === value ? { default_freeleech: 0 } : {}),
    })
  }
  const add = () => {
    if (!canAdd) return
    onChange({ freeleech_options: [...options, customValue] })
    setCustom('')
  }

  return (
    <div className="grid gap-2 rounded-md border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{t('trackers.freeleech')}</span>
        <span className="text-xs text-muted-foreground">{t('trackers.freeleechHelp')}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex flex-wrap overflow-hidden rounded-md border">
          {all.map((value) => {
            const on = options.includes(value)
            return (
              <button
                key={value}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(value)}
                className={cn(
                  'flex h-8 items-center gap-1 border-r px-3 text-xs tabular-nums last:border-r-0',
                  on ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:bg-muted',
                )}
              >
                {on && <CheckIcon className="size-3" />}
                {value}%
              </button>
            )
          })}
        </div>
        <div className="flex items-center">
          <Input
            className="h-8 w-20 rounded-r-none text-xs"
            inputMode="numeric"
            placeholder="%"
            aria-label={t('trackers.freeleechOther')}
            value={custom}
            onChange={(e) => setCustom(e.target.value.replace(/\D/g, '').slice(0, 3))}
            onKeyDown={(e) => e.key === 'Enter' && add()}
          />
          <Button variant="outline" size="icon" className="size-8 rounded-l-none border-l-0" disabled={!canAdd} onClick={add}>
            <PlusIcon className="size-3.5" />
          </Button>
        </div>
        {options.length > 0 && (
          <div className="ml-auto flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">{t('trackers.freeleechDefault')}</span>
            <Select value={String(defaultValue)} onValueChange={(v) => v != null && onChange({ default_freeleech: Number(v) })}>
              <SelectTrigger size="sm" className="w-24">
                <SelectValue>{(v: string | null) => (v == null || v === '0' ? t('trackers.freeleechNone') : `${v}%`)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {[0, ...options].map((value) => (
                  <SelectItem key={value} value={String(value)}>
                    {value === 0 ? t('trackers.freeleechNone') : `${value}%`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    </div>
  )
}
