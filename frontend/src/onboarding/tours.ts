import type { OnboardingState } from '@/onboarding/state'

// Una condizione sul DOM o sulla configurazione:
// - element: l'ancora c'è (es. il dialog si è aperto);
// - gone: l'ancora non c'è più (es. il dialog si è chiuso);
// - filled: l'ancora ha data-tour-filled="true" (es. la cartella è scelta);
// - status: il passo di setup-status è fatto.
export type Condition = { element: string } | { gone: string } | { filled: string } | { status: string }

export interface TourStep {
  id: string // testi: onboarding.tour.<tour>.<id>.title / .body
  anchor?: string // data-tour da evidenziare; senza, il fumetto è al centro
  side?: 'top' | 'right' | 'bottom' | 'left'
  // Avanza da solo quando la condizione è vera; senza "next" il pulsante
  // Next non c'è: si va avanti facendo la cosa (es. cliccare Add).
  waitFor?: Condition
  next?: boolean
  // Salta il passo (a skipTo, o al successivo) se è già vero.
  skipIf?: Condition
  skipTo?: string
  // Se l'ancora sparisce (es. il dialog chiuso a metà), torna a questo passo.
  backTo?: string
  // Solo con questa risposta del benvenuto.
  when?: keyof OnboardingState['answers']
  // La schermata del passo, se non è quella del tour (tour delle viste).
  route?: string
}

export interface Tour {
  key: string // lo stesso del passo della checklist (o "views")
  route: string
  steps: TourStep[]
  // Il tour che segue questo, invece del prossimo passo della checklist;
  // last: nessuno, si torna alla dashboard.
  then?: string
  last?: boolean
}

const dialogStep = (tour: string, id: string, back: string): TourStep => ({
  id, anchor: `${tour}.dialog.${id}`, side: 'right', next: true, backTo: back,
})

export const TOURS: Tour[] = [
  {
    key: 'storage',
    route: '/config?tab=storage',
    steps: [
      { id: 'intro', anchor: 'storage.card', side: 'bottom', next: true },
      { id: 'add', anchor: 'storage.add', side: 'left', waitFor: { element: 'storage.dialog' },
        skipIf: { element: 'storage.row' }, skipTo: 'media' },
      dialogStep('storage', 'label', 'add'),
      dialogStep('storage', 'root', 'add'),
      { id: 'create', anchor: 'storage.dialog.create', side: 'top', backTo: 'add',
        waitFor: { element: 'storage.row' } },
      { id: 'media', anchor: 'storage.media-folder', side: 'bottom', next: true,
        waitFor: { filled: 'storage.media-folder' } },
      { id: 'seeding', anchor: 'storage.seeding-folder', side: 'bottom', next: true,
        waitFor: { filled: 'storage.seeding-folder' } },
      { id: 'new', anchor: 'storage.new-folder', side: 'bottom', next: true },
      { id: 'upload', anchor: 'storage.upload-folder', side: 'bottom', next: true, when: 'upload' },
      { id: 'watch', anchor: 'storage.watch-folder', side: 'bottom', next: true, when: 'upload' },
      { id: 'verify', anchor: 'storage.verify', side: 'left', next: true },
    ],
  },
  {
    key: 'clients',
    route: '/config?tab=clients',
    steps: [
      { id: 'add', anchor: 'clients.add', side: 'left', waitFor: { element: 'clients.dialog' },
        skipIf: { element: 'clients.card' }, skipTo: 'test' },
      dialogStep('clients', 'type', 'add'),
      dialogStep('clients', 'url', 'add'),
      dialogStep('clients', 'credentials', 'add'),
      { id: 'create', anchor: 'clients.dialog.create', side: 'top', backTo: 'add',
        waitFor: { element: 'clients.card' } },
      { id: 'test', anchor: 'clients.test', side: 'top', next: true },
      // Facoltativo: senza dischi scelti il client vale per tutti (stessi percorsi).
      { id: 'disks', anchor: 'clients.disks', side: 'top', next: true },
      { id: 'labels', anchor: 'clients.labels', side: 'top', next: true, when: 'upload' },
    ],
  },
  {
    key: 'metadata',
    route: '/config?tab=integrations',
    steps: [
      { id: 'tmdb', anchor: 'metadata.tmdb', side: 'bottom', next: true, waitFor: { status: 'metadata' } },
      { id: 'tvdb', anchor: 'metadata.tvdb', side: 'bottom', next: true },
      { id: 'radarr', anchor: 'integrations.radarr', side: 'top', next: true, when: 'arr' },
      { id: 'sonarr', anchor: 'integrations.sonarr', side: 'top', next: true, when: 'arr' },
    ],
  },
  {
    key: 'trackers',
    route: '/config?tab=trackers',
    steps: [
      { id: 'add', anchor: 'trackers.add', side: 'left', waitFor: { element: 'trackers.dialog' },
        skipIf: { element: 'trackers.card' }, skipTo: 'client' },
      dialogStep('trackers', 'preset', 'add'),
      dialogStep('trackers', 'url', 'add'),
      dialogStep('trackers', 'token', 'add'),
      dialogStep('trackers', 'announce', 'add'),
      { id: 'create', anchor: 'trackers.dialog.create', side: 'top', backTo: 'add',
        waitFor: { element: 'trackers.card' } },
      { id: 'client', anchor: 'trackers.card.client', side: 'right', next: true },
      { id: 'language', anchor: 'trackers.card.language', side: 'right', next: true },
      { id: 'seed', anchor: 'trackers.card.seed', side: 'right', next: true },
      { id: 'profile', anchor: 'trackers.card.profile', side: 'top', next: true, when: 'upload' },
    ],
  },
  {
    key: 'exclusions',
    route: '/config?tab=exclusions',
    steps: [
      { id: 'presets', anchor: 'exclusions.presets', side: 'right', next: true },
      { id: 'custom', anchor: 'exclusions.custom', side: 'left', next: true },
    ],
  },
  {
    key: 'reseeding',
    route: '/config?tab=matching',
    steps: [
      { id: 'search', anchor: 'reseeding.search', side: 'right', next: true },
      { id: 'thresholds', anchor: 'reseeding.thresholds', side: 'right', next: true },
      { id: 'execution', anchor: 'reseeding.execution', side: 'left', next: true },
    ],
  },
  {
    key: 'upload',
    route: '/config?tab=images',
    steps: [
      { id: 'hosts', anchor: 'upload.image-hosts', side: 'bottom', next: true },
      { id: 'screenshots', anchor: 'upload.screenshots', side: 'right', next: true },
      { id: 'releases', anchor: 'upload.releases', side: 'right', next: true, route: '/config?tab=releases' },
      { id: 'description', anchor: 'upload.description', side: 'left', next: true, route: '/config?tab=releases' },
      { id: 'names', anchor: 'upload.file-names', side: 'top', next: true, route: '/config?tab=releases' },
      { id: 'single_file', anchor: 'upload.single-file', side: 'top', next: true, route: '/config?tab=releases' },
    ],
  },
  {
    key: 'first_scan',
    route: '/dashboard',
    then: 'views',
    steps: [
      { id: 'run', anchor: 'dashboard.run', side: 'bottom', waitFor: { filled: 'dashboard.run' },
        skipIf: { status: 'first_scan' }, skipTo: 'progress' },
      { id: 'progress', side: 'bottom', next: true },
    ],
  },
  {
    // Il giro delle viste, dopo la prima scansione: non è un passo della checklist.
    key: 'views',
    route: '/dashboard',
    last: true,
    steps: [
      { id: 'intro', next: true },
      { id: 'health', anchor: 'views.health', side: 'right', next: true },
      { id: 'metrics', anchor: 'views.metrics', side: 'bottom', next: true },
      { id: 'changes', anchor: 'views.changes', side: 'top', next: true },
      { id: 'filter', anchor: 'views.tracker-filter', side: 'left', next: true },
      { id: 'library', anchor: 'views.library-switch', side: 'bottom', next: true, route: '/library/folder' },
      { id: 'states', anchor: 'views.summary', side: 'bottom', next: true, route: '/library/folder' },
      { id: 'pack', anchor: 'views.pack', side: 'left', next: true, route: '/library/folder', when: 'upload' },
      { id: 'torrents', anchor: 'views.torrent-switch', side: 'bottom', next: true, route: '/torrent/folder' },
      { id: 'not_imported', anchor: 'views.summary', side: 'bottom', next: true, route: '/torrent/triage' },
      { id: 'uploads', anchor: 'views.uploads', side: 'bottom', next: true, route: '/upload', when: 'upload' },
      { id: 'review', anchor: 'views.review', side: 'top', next: true, route: '/reseeding' },
    ],
  },
]

export function tourFor(key: string): Tour | undefined {
  return TOURS.find((tour) => tour.key === key)
}

// I passi di un tour per queste risposte del benvenuto.
export function stepsFor(tour: Tour, answers: OnboardingState['answers']): TourStep[] {
  return tour.steps.filter((step) => !step.when || answers[step.when])
}

export const selector = (anchor: string) => `[data-tour="${anchor}"]`

export function check(
  condition: Condition,
  root: ParentNode,
  status: Record<string, { done: boolean }> | undefined,
): boolean {
  if ('element' in condition) return root.querySelector(selector(condition.element)) !== null
  if ('gone' in condition) return root.querySelector(selector(condition.gone)) === null
  if ('filled' in condition) return root.querySelector(`${selector(condition.filled)}[data-tour-filled="true"]`) !== null
  return status?.[condition.status]?.done ?? false
}
