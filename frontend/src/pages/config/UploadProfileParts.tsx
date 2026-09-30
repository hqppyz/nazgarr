import { useState, type ReactNode } from 'react'

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
// (campo UNIT3D "free"): quelle comuni come interruttori, più una a scelta;
// e quella preselezionata negli upload. Nessuna = il tracker non lo concede.
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
  const toggle = (value: number) => {
    const next = options.includes(value) ? options.filter((v) => v !== value) : [...options, value]
    onChange({ freeleech_options: next, ...(options.includes(value) && defaultValue === value ? { default_freeleech: 0 } : {}) })
  }
  return (
    <div className="grid gap-2">
      <div>
        <Label>{t('trackers.freeleech')}</Label>
        <p className="text-xs text-muted-foreground">{t('trackers.freeleechHelp')}</p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {all.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={options.includes(value)}
            onClick={() => toggle(value)}
            className={cn(
              'rounded-md border px-2.5 py-1 text-xs tabular-nums',
              options.includes(value) ? 'border-primary bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted',
            )}
          >
            {value}%
          </button>
        ))}
        <Input
          className="h-7 w-20 text-xs"
          inputMode="numeric"
          placeholder={t('trackers.freeleechOther')}
          value={custom}
          onChange={(e) => setCustom(e.target.value.replace(/\D/g, ''))}
          onKeyDown={(e) => {
            const value = Number(custom)
            if (e.key === 'Enter' && value > 0 && value <= 100 && !options.includes(value)) {
              onChange({ freeleech_options: [...options, value] })
              setCustom('')
            }
          }}
        />
      </div>
      {options.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">{t('trackers.freeleechDefault')}</span>
          {[0, ...options].map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={defaultValue === value}
              onClick={() => onChange({ default_freeleech: value })}
              className={cn(
                'rounded-md border px-2 py-0.5 tabular-nums',
                defaultValue === value ? 'border-primary bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted',
              )}
            >
              {value === 0 ? t('trackers.freeleechNone') : `${value}%`}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
