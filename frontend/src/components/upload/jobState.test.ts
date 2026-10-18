import { describe, expect, it } from 'vitest'

import { currentRunEvents } from '@/components/upload/jobState'

const events = (...codes: string[]) => codes.map((code, id) => ({ id, code }))

describe('currentRunEvents', () => {
  it('reads the steps of the run in progress only', () => {
    const run = events('job_queued', 'execution_started', 'torrent_created', 'job_partial', 'job_retried',
      'execution_started', 'torrent_created')
    expect(currentRunEvents(run).map((event) => event.id)).toEqual([5, 6])
  })

  it('shows nothing done yet while a retried or resumed upload waits in the queue', () => {
    for (const restart of ['job_retried', 'job_resumed_by_user', 'job_resumed']) {
      const run = events('execution_started', 'torrent_created', 'screenshots_done', 'job_failed', restart)
      expect(currentRunEvents(run).map((event) => event.code)).toEqual([restart])
    }
  })

  it('keeps every event before the first run', () => {
    const run = events('job_created', 'analysis_done')
    expect(currentRunEvents(run)).toEqual(run)
  })
})
