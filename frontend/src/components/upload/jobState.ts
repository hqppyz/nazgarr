// Lo stato di un upload letto dai suoi target, con le stesse regole del
// backend (nazgarr/upload/jobs.py): la pagina offre solo quello che il
// server accetterà.

interface TargetLike {
  status: string
  action?: string | null
  torrent_id_remote?: string | null
  error_message?: string | null
}

// Un target in questi stati lo sta lavorando l'esecuzione, anche in un job
// appena annullato (BUSY_TARGET_STATES): né eliminarlo né riprenderlo.
export const BUSY_TARGET_STATES = ['preparing', 'uploading', 'seeding']

export function isBusy(job: { targets: TargetLike[] }) {
  return job.targets.some((target) => BUSY_TARGET_STATES.includes(target.status))
}

// I tracker che "Riprova" rifà (retryable_targets): falliti prima di
// pubblicare, con un upload o un reseed da fare. Uno pubblicato ma non in
// seed ha "Riprova il seed".
export function retryableTargets<T extends TargetLike>(job: { status: string; targets: T[] }): T[] {
  if (!['failed', 'partial'].includes(job.status)) return []
  return job.targets.filter(
    (target) =>
      target.status === 'failed' && (target.action === 'upload' || target.action === 'reseed') && !target.torrent_id_remote,
  )
}

// Un invio fermato da un riavvio: non si sa se il tracker l'ha ricevuto
// (needs_confirmation), si riprova solo dopo averlo controllato sul tracker.
export function needsConfirmation(target: TargetLike) {
  return target.action === 'upload' && target.error_message === 'interrupted'
}

// Gli eventi dell'ultima esecuzione: dopo un nuovo tentativo ce n'è più
// d'una, e gli step (hash, screenshot) si leggono solo da quella in corso.
export function currentRunEvents<E extends { code: string }>(events: E[]): E[] {
  const start = events.map((event) => event.code).lastIndexOf('execution_started')
  return start < 0 ? events : events.slice(start)
}
