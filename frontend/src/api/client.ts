import createClient from 'openapi-fetch'
import type { FetchResponse } from 'openapi-fetch'
import type { MediaType } from 'openapi-typescript-helpers'

import { olderRemoteFallback } from '@/api/compat'
import { clearToken, getToken } from '@/lib/authToken'
import { demoResponse } from '@/lib/uploadDemo'
import { instancePath } from '@/lib/instance'
import { t } from '@/lib/i18n'

import type { components, paths } from './schema'

export type Schemas = components['schemas']

// baseUrl vuota: le path dello schema OpenAPI includono già il prefisso
// /api di FastAPI (es. "/api/disks") - risolte relative all'origine
// corrente, così il proxy di Vite (vite.config.ts, solo dev) e il mount
// statico di FastAPI (produzione, stesso container) funzionano identici
// senza bisogno di CORS.
export const api = createClient<paths>({ baseUrl: '' })

// Allega il token a ogni richiesta. Il login è obbligatorio (nazgarr/web/auth.py,
// mai una modalità aperta): senza token ogni endpoint fuori da /api/auth
// risponde 401. Un 401 con il codice di una sessione scaduta o revocata
// scarta il token: AuthGate lo rileva al prossimo controllo e rimanda al
// login, invece di continuare a mandare un token ormai invalido. Gli altri
// 401 non toccano la sessione (isSessionFailure).
api.use({
  onRequest({ request }) {
    // L'upload di esempio del tour: le sue richieste non arrivano mai al server.
    const demo = demoResponse(request)
    if (demo) return demo
    const token = getToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    // Un'altra istanza: la stessa chiamata, attraverso il proxy di questa.
    const url = new URL(request.url)
    const path = instancePath(url.pathname)
    if (path === url.pathname) return request
    url.pathname = path
    return rerouted(request, url)
  },
  async onResponse({ request, response, schemaPath, options }) {
    // Un endpoint che un'istanza remota più vecchia non ha: la stessa
    // risposta da quello di prima (src/api/compat.ts).
    const final = (await olderRemoteFallback(schemaPath, request, response, options.fetch)) ?? response
    if (final.status === 401 && (await isSessionFailure(final))) clearToken()
    return final
  },
})

// La stessa richiesta verso un altro URL. Non `new Request(url, request)`:
// con una Request al posto delle opzioni, metodo, header e corpo passano
// solo dove le sue proprietà si leggono come un dizionario (non in undici),
// e il corpo diventa uno stream, che vuole `duplex` e HTTP/2 in Chrome e che
// Firefox e Safari non mandano. Il corpo si legge qui, una volta: sono JSON
// piccoli (audit 2026-10-18).
async function rerouted(request: Request, url: URL): Promise<Request> {
  const buffer = request.method === 'GET' || request.method === 'HEAD' ? null : await request.arrayBuffer()
  return new Request(url, {
    method: request.method,
    headers: request.headers,
    body: buffer && buffer.byteLength > 0 ? buffer : undefined,
    signal: request.signal,
    credentials: request.credentials,
    cache: request.cache,
    redirect: request.redirect,
  })
}

// Le due risposte di questa istanza a una sessione che non vale più
// (nazgarr/web/auth.py::require_auth, nazgarr/api/auth.py::me).
const SESSION_CODES = new Set(['auth_required', 'auth_setup_required'])

// Non ogni 401 è una sessione finita: la password attuale sbagliata nel
// cambio password (auth_wrong_current_password) o al login
// (auth_invalid_credentials), o, attraverso il proxy di un'altra istanza, la
// sua API key cambiata o revocata (api_key_invalid). Scartare il token lì
// butterebbe fuori da questa istanza per un errore di battitura o per
// un'istanza remota. Solo i codici di una sessione scaduta scartano il token,
// locali o remoti che siano (audit 2026-10-18).
async function isSessionFailure(response: Response): Promise<boolean> {
  try {
    const body = (await response.clone().json()) as { detail?: { code?: unknown } } | null
    const code = body?.detail?.code
    return typeof code === 'string' && SESSION_CODES.has(code)
  } catch {
    return false
  }
}

/**
 * L'errore di una chiamata alle API: il messaggio già tradotto, più lo stato
 * HTTP e il codice dell'errore (`detail.code`, nazgarr/core/errors.py) per chi
 * deve distinguere i casi (un 404 da un 500, una sessione scaduta da una API
 * key di un'altra istanza) senza confrontare il testo.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string | undefined

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/**
 * Estrae `data` da una risposta openapi-fetch, o lancia un ApiError col
 * messaggio d'errore se la richiesta è fallita — così ogni mutation può
 * semplicemente fare `await unwrap(api.POST(...))` e lasciare che
 * TanStack Query gestisca l'errore, senza ripetere questo controllo in
 * ogni hook. Tipizzato esattamente come il valore di ritorno di
 * api.GET/POST/... (FetchResponse di openapi-fetch), non una forma
 * scritta a mano — altrimenti TS non riesce a inferire T correttamente
 * (weak-type check su un'unione discriminata senza proprietà realmente
 * in comune tra i due rami).
 *
 * Il backend (nazgarr/core/errors.py) restituisce `{"detail": {"code", "params"}}`
 * per ogni errore autorato — mai testo libero — tradotto qui in inglese via
 * t('errors.' + code, params). Un `detail` stringa semplice (validazione
 * pydantic 422, o un messaggio già in inglese proveniente da un servizio
 * esterno) passa invece così com'è.
 */
export async function unwrap<T extends Record<string | number, unknown>, O, M extends MediaType>(
  promise: Promise<FetchResponse<T, O, M>>,
): Promise<NonNullable<FetchResponse<T, O, M>['data']>> {
  const { data, error, response } = await promise
  if (error !== undefined) {
    const status = response.status
    const detail = (error as { detail?: unknown } | undefined)?.detail
    if (detail !== null && typeof detail === 'object' && 'code' in detail && typeof detail.code === 'string') {
      const { code, params } = detail as { code: string; params?: Record<string, unknown> }
      throw new ApiError(t(`errors.${code}`, params), status, code)
    }
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(error), status)
  }
  return data as NonNullable<typeof data>
}

// Quante volte ripetere una query fallita (defaultOptions di main.tsx). Un 4xx
// è una risposta, non un guasto: un upload cancellato resta 404, una chiave
// in sola lettura resta 403, e ripetere tre volte (1+2+4 s) fa solo aspettare
// "Caricamento…" per un errore già noto. Si ripetono la rete caduta, i 5xx e
// i due 4xx che passano da soli (408 timeout, 429 troppe richieste).
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429) {
    return false
  }
  return failureCount < 3
}
