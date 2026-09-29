import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ID_FIELDS, type ForcedIdsDraft } from '@/lib/upload'

export function ForcedIdFields({ ids, onChange }: { ids: ForcedIdsDraft; onChange: (ids: ForcedIdsDraft) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-4">
      {ID_FIELDS.map((field) => (
        <div key={field.key} className="grid gap-1.5">
          <Label htmlFor={`forced-${field.key}`}>{field.label}</Label>
          <Input
            id={`forced-${field.key}`}
            className="font-mono text-xs"
            placeholder={field.placeholder}
            value={ids[field.key]}
            inputMode={field.key === 'tvdb' || field.key === 'mal' ? 'numeric' : undefined}
            onChange={(e) => onChange({ ...ids, [field.key]: e.target.value })}
          />
        </div>
      ))}
    </div>
  )
}
