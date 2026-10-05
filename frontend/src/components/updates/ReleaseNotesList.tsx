import { TriangleAlertIcon } from 'lucide-react'

import type { Schemas } from '@/api/client'
import { currentLocale, t } from '@/lib/i18n'

type Note = Schemas['ReleaseNote']

// Le note di una o più versioni (nazgarr/release_notes.json): i cambiamenti
// che chiedono qualcosa all'utente per primi, poi i punti salienti. Nella
// lingua dell'interfaccia, o in inglese se manca.
function localized(map: Record<string, string[]> | undefined): string[] {
  if (!map) return []
  return map[currentLocale()] ?? map.en ?? []
}

export function hasBreaking(notes: Note[]): boolean {
  return notes.some((note) => localized(note.breaking).length > 0)
}

export function ReleaseNotesList({ notes }: { notes: Note[] }) {
  return (
    <div className="grid gap-4">
      {notes.map((note) => {
        const breaking = localized(note.breaking)
        const highlights = localized(note.highlights)
        const fixes = localized(note.fixes)
        return (
          <section key={note.version} className="grid gap-2">
            <p className="text-sm font-medium">
              {t('updates.version', { version: note.version })}
              {note.date && <span className="ml-2 text-xs font-normal text-muted-foreground">{note.date}</span>}
            </p>
            {breaking.length > 0 && (
              <div className="grid gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                <p className="flex items-center gap-2 font-medium">
                  <TriangleAlertIcon className="size-4 shrink-0 text-amber-600 dark:text-amber-400" />
                  {t('updates.breaking')}
                </p>
                <ul className="list-disc pl-5">
                  {breaking.map((line) => <li key={line}>{line}</li>)}
                </ul>
              </div>
            )}
            {[['new', highlights], ['fixes', fixes]].map(([kind, lines]) => (lines as string[]).length > 0 && (
              <div key={kind as string} className="grid gap-1">
                <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{t(`updates.${kind}`)}</p>
                <ul className="list-disc pl-5 text-sm">
                  {(lines as string[]).map((line) => <li key={line}>{line}</li>)}
                </ul>
              </div>
            ))}
          </section>
        )
      })}
    </div>
  )
}
