import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Schemas } from '@/api/client'
import { MigrationBackupBox } from '@/pages/config/MigrationBackupBox'

const base: Schemas['AppInfoResponse'] = {
  version: '0.9.20',
  commit: null,
  python_version: '3.12.7',
  platform: 'linux/x86_64',
  started_at: '2026-10-22T10:00:00Z',
  backups_dir: '/app/config/data/backups',
  backups_keep: 3,
  migration_backup: null,
}

describe('MigrationBackupBox', () => {
  it('says where the backups go even before the first one', () => {
    render(<MigrationBackupBox info={base} />)
    expect(screen.getByText(/None yet/)).toBeInTheDocument()
    expect(screen.getByText('/app/config/data/backups')).toBeInTheDocument()
    expect(screen.getByText(/The last 3 are kept/)).toBeInTheDocument()
  })

  it('shows the last backup, its versions, and when its file is gone', () => {
    const file = 'pre-migration-v12-to-v13-0.9.20-20261022T101500Z.db'
    render(
      <MigrationBackupBox
        info={{
          ...base,
          migration_backup: {
            path: `/app/config/data/backups/${file}`, file, from_version: 12, to_version: 13,
            created_at: '2026-10-22T10:15:00+00:00', exists: false,
          },
        }}
      />,
    )
    expect(screen.getByText(file)).toBeInTheDocument()
    expect(screen.getByText(/database version 12 → 13/)).toBeInTheDocument()
    expect(screen.getByText('The file is no longer there.')).toBeInTheDocument()
    expect(screen.queryByText(/None yet/)).toBeNull()
  })
})
