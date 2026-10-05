// L'istanza che l'interfaccia sta guardando (nazgarr/integrations/instances.py): questa, o
// un'altra registrata in Configurazione › Istanze. Con un'altra, ogni chiamata
// alle API passa da questa istanza (/api/remote/{id}/…), che la inoltra con la
// API key di quella: il browser non la vede mai.
//
// La scelta sta nel browser (localStorage) e cambiarla ricarica la pagina:
// cache, query e tour ripartono puliti per l'istanza nuova.

const KEY = 'nazgarr-instance'

// Restano sempre di questa istanza: il login, il registro delle istanze, il
// proxy stesso.
const LOCAL = ['/api/auth', '/api/instances', '/api/remote']

export function activeInstanceId(): number | null {
  try {
    const raw = window.localStorage.getItem(KEY)
    const id = raw ? Number(raw) : NaN
    return Number.isInteger(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

export function isRemote(): boolean {
  return activeInstanceId() !== null
}

export function switchInstance(id: number | null, to = '/dashboard') {
  try {
    if (id === null) window.localStorage.removeItem(KEY)
    else window.localStorage.setItem(KEY, String(id))
  } catch {
    // senza storage resta su questa istanza
  }
  window.location.assign(to)
}

// "/api/disks?x=1" → "/api/remote/3/api/disks?x=1" se si guarda l'istanza 3.
export function instancePath(path: string, id: number | null = activeInstanceId()): string {
  if (id === null || !path.startsWith('/api/') || LOCAL.some((p) => path === p || path.startsWith(`${p}/`))) {
    return path
  }
  return `/api/remote/${id}${path}`
}
