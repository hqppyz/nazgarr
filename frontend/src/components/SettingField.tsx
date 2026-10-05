import { useState } from 'react'
import { toast } from 'sonner'

import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { InfoPopover } from '@/components/InfoPopover'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { t } from '@/lib/i18n'

export function SettingField({
  settingKey,
  label,
  description,
  type = 'text',
  placeholder,
  compact = false,
}: {
  settingKey: string
  label: string
  description: string
  type?: 'text' | 'password' | 'number'
  placeholder?: string
  // Una riga sola (nome + input + Salva) invece di etichetta/descrizione
  // impilate sopra — per liste lunghe (es. le chiavi API dei provider
  // immagine) dove lo spazio verticale conta più della descrizione estesa.
  compact?: boolean
}) {
  const { data, isPending } = useSetting(settingKey)
  const setSetting = useSetSetting(settingKey)
  // null = l'utente non ha ancora toccato il campo: mostra il valore dal
  // server. Evita di sincronizzare data->stato locale con un effect (mai
  // necessario qui, derivabile direttamente durante il render).
  const [draft, setDraft] = useState<string | null>(null)
  const value = draft ?? data?.value ?? ''

  function save() {
    setSetting.mutate(value, {
      onSuccess: () => {
        toast.success(t('common.itemSaved', { item: label }))
        setDraft(null)
      },
      onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
    })
  }

  if (compact) {
    // Da telefono etichetta (w-28, troncata) + input + Salva su una riga non
    // ci stanno: l'etichetta va sopra, con la descrizione visibile (il title
    // al tocco non si vede); da sm la riga di sempre, la descrizione si apre
    // anche al tocco.
    return (
      <div className="grid gap-1 sm:flex sm:items-center sm:gap-2">
        <span className="hidden w-28 shrink-0 sm:block">
          <InfoPopover content={description} className="block truncate">
            <Label htmlFor={settingKey} className="block truncate text-xs">
              {label}
            </Label>
          </InfoPopover>
        </span>
        <Label htmlFor={settingKey} className="text-xs sm:hidden">
          {label}
        </Label>
        <p className="text-xs break-words text-muted-foreground sm:hidden">{description}</p>
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Input
            id={settingKey}
            type={type}
            value={value}
            placeholder={isPending ? t('common.loading') : placeholder}
            onChange={(e) => setDraft(e.target.value)}
            className="h-8"
          />
          <Button variant="outline" size="sm" disabled={setSetting.isPending} onClick={save}>
            {t('common.save')}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={settingKey}>{label}</Label>
      <p className="text-xs text-muted-foreground">{description}</p>
      <div className="flex items-center gap-2">
        <Input
          id={settingKey}
          type={type}
          value={value}
          placeholder={isPending ? t('common.loading') : placeholder}
          onChange={(e) => setDraft(e.target.value)}
        />
        <Button variant="outline" disabled={setSetting.isPending} onClick={save}>
          {t('common.save')}
        </Button>
      </div>
    </div>
  )
}
