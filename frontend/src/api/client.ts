import createClient from 'openapi-fetch'
import type { FetchResponse } from 'openapi-fetch'
import type { MediaType } from 'openapi-typescript-helpers'

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

// Allega il token a ogni richiesta se presente — un'istanza senza login
// mai configurato (nazgarr/web/auth.py) non ne ha uno, e ogni endpoint resta
// raggiungibile esattamente come prima di questa fase. Su 401 il token
// viene scartato: AuthGate lo rileva al prossimo controllo e rimanda al
// login, invece di continuare a rimandare un token ormai invalido/scaduto.
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
    if (path !== url.pathname) {
      url.pathname = path
      return new Request(url, request)
    }
    return request
  },
  onResponse({ response }) {
    if (response.status === 401) clearToken()
    return response
  },
})

/**
 * Estrae `data` da una risposta openapi-fetch, o lancia un Error col
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
  const { data, error } = await promise
  if (error !== undefined) {
    const detail = (error as { detail?: unknown } | undefined)?.detail
    if (detail !== null && typeof detail === 'object' && 'code' in detail && typeof detail.code === 'string') {
      const { code, params } = detail as { code: string; params?: Record<string, unknown> }
      throw new Error(t(`errors.${code}`, params))
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(error))
  }
  return data as NonNullable<typeof data>
}
