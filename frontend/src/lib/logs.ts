// Il nome del logger, corto: senza "app.", e le librerie con un nome umano.
export function shortLogger(name: string): string {
  if (name.startsWith('apscheduler')) return 'scheduler'
  if (name === 'uvicorn.access') return 'http'
  if (name.startsWith('uvicorn')) return 'server'
  const parts = name.replace(/^app\./, '').split('.')
  return parts.slice(-2).join('.')
}
