// Il nome del logger, corto: senza "nazgarr." ("app." nei log di prima del
// rinomino del modulo), e le librerie con un nome umano.
export function shortLogger(name: string): string {
  if (name.startsWith('apscheduler')) return 'scheduler'
  if (name === 'uvicorn.access') return 'http'
  if (name.startsWith('uvicorn')) return 'server'
  // Il sottopacchetto (nazgarr.reseed.pipeline) non serve a riconoscere il
  // modulo; upload sì, al posto del vecchio prefisso upload_ (upload.execute).
  const parts = name
    .replace(/^(nazgarr|app)\./, '')
    .replace(/^(core|web|library|torrents|reseed|integrations)\./, '')
    .split('.')
  return parts.slice(-2).join('.')
}
