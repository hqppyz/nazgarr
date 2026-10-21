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

// Non si sa se il tracker l'ha ricevuto (UNSURE_ERRORS, needs_confirmation):
// un invio fermato da un riavvio, o fallito dopo che la richiesta era
// partita. Si riprova solo dopo averlo controllato sul tracker.
const UNSURE_ERRORS = ['interrupted', 'upload_outcome_unknown']

export function needsConfirmation(target: TargetLike) {
  return target.action === 'upload' && UNSURE_ERRORS.includes(target.error_message ?? '')
}

// "Riprova il seed" (execute.py::retry_seed, SEED_RETRYABLE): un upload
// pubblicato ma non in seed, o un torrent fermo dopo un recheck fallito, anche
// di un reseed. Mai mentre il recheck è in corso (seed_recheck_pending): lì
// Nazgarr aspetta l'esito e avvia il torrent da sé.
const SEED_RETRYABLE = ['seed_failed', 'no_client', 'seed_recheck_failed']

export function canRetrySeed(target: TargetLike) {
  const code = target.error_message ?? ''
  return target.status === 'done' && SEED_RETRYABLE.includes(code)
    && (target.action === 'upload' || code === 'seed_recheck_failed')
}

// Dove comincia un'esecuzione: dopo "Riprova", una ripresa o un riavvio il
// job torna in coda, e finché il worker non lo prende gli step sono da fare.
const RUN_STARTS = ['execution_started', 'job_retried', 'job_resumed_by_user', 'job_resumed']

// Gli eventi dell'ultima esecuzione: dopo un nuovo tentativo ce n'è più
// d'una, e gli step (hash, screenshot) si leggono solo da quella in corso.
export function currentRunEvents<E extends { code: string }>(events: E[]): E[] {
  const codes = events.map((event) => event.code)
  const start = Math.max(...RUN_STARTS.map((code) => codes.lastIndexOf(code)))
  return start < 0 ? events : events.slice(start)
}
