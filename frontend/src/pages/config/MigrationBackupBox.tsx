import { DatabaseBackupIcon } from 'lucide-react'

import type { Schemas } from '@/api/client'
import { t, uiLocale } from '@/lib/i18n'
import { parseApiDate } from '@/lib/time'

// Il backup che Nazgarr fa prima di aggiornare il database, quando
// l'aggiornamento lo cambia (nazgarr/core/db_backup.py): solo informativo,
// con dove sta. Il ripristino si fa dal CLI, con Nazgarr fermo.
export function MigrationBackupBox({ info }: { info: Schemas['AppInfoResponse'] }) {
  const backup = info.migration_backup
  const date = backup?.created_at
    ? parseApiDate(backup.created_at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' })
    : '—'
  return (
    <div className="grid gap-1.5 rounded-md border p-3 text-sm">
      <div className="flex items-center gap-2 font-medium">
        <DatabaseBackupIcon className="size-4 shrink-0 text-muted-foreground" />
        {t('application.dbBackupTitle')}
      </div>
      {backup ? (
        <>
          <p className="font-mono text-xs break-all">{backup.file}</p>
          <p className="text-xs text-muted-foreground">
            {t('application.dbBackupDetails', { date, from: backup.from_version ?? '?', to: backup.to_version ?? '?' })}
          </p>
          {!backup.exists && (
            <p className="text-xs text-amber-700 dark:text-amber-400">{t('application.dbBackupMissing')}</p>
          )}
        </>
      ) : (
        <p className="text-xs text-muted-foreground">{t('application.dbBackupNone')}</p>
      )}
      <p className="text-xs text-muted-foreground">
        {t('application.dbBackupFolder')}: <span className="font-mono break-all text-foreground">{info.backups_dir}</span>
      </p>
      <p className="text-xs text-muted-foreground">
        {t('application.dbBackupKeep', { keep: info.backups_keep })} {t('application.dbBackupRestore')}
      </p>
    </div>
  )
}
