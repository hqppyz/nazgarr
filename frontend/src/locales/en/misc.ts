// Etichette che erano scritte direttamente nei componenti: navigazione,
// titoli di schede, livelli dei log.
export const misc = {
  'nav.dashboard': 'Dashboard',
  'nav.library': 'Library',
  'nav.folderView': 'Folder view',
  'nav.posterView': 'Poster view',
  'nav.torrent': 'Torrent',
  'nav.files': 'Files',
  'nav.notImported': 'Triage',
  'nav.reseeding': 'Reseeding',
  'nav.upload': 'Upload',
  'nav.configuration': 'Configuration',
  'misc.review': 'Review',
  'misc.schedule': 'Schedule',
  // Un cron salvato che non si legge: nessuna scansione parte da sola (audit 2026-10-18).
  'misc.scheduleInvalid': 'invalid',
  'misc.scheduleInvalidDetail': 'The saved schedule "{cron}" cannot be read ({error}), so no scan runs on its own. Pick one of the choices or save a new cron.',
  'logs.levelVerbose': 'Verbose',
  'logs.levelInfo': 'Info',
  'logs.levelWarning': 'Warning',
  'logs.levelError': 'Error',
} as const
