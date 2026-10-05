import { useSyncExternalStore } from 'react'

import demo from '@/lib/uploadDemo.json'

// L'upload di esempio del tour (decisione dell'utente, 2026-10-05): le vere
// schermate di conferma del match e di decisione, con i dati di
// uploadDemo.json (generati dall'API vera da tests/test_upload_demo.py).
// Mentre la pagina di esempio è aperta, le richieste che riguardano
// l'upload 0 (nessun job vero ha quell'id) e i metadati si servono da qui:
// nessun job nel database, nessuna ricerca TMDB, nessun tracker o client.
// Una scrittura (conferma del match, approvazione) fa solo avanzare l'esempio.

export const DEMO_UPLOAD_ID = 0

type DemoStep = 'match' | 'decision' | 'approved'

let active = false
let step: DemoStep = 'match'
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((listener) => listener())

export function startUploadDemo(from: DemoStep = 'match') {
  active = true
  step = from
  emit()
}

export function stopUploadDemo() {
  active = false
  emit()
}

export function useUploadDemoStep(): DemoStep {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => step,
  )
}

const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const job = () => (step === 'match' ? demo.match : demo.decision)

const UPLOAD = new RegExp(`^/api/uploads/${DEMO_UPLOAD_ID}(/.*)?$`)

// La risposta finta per una richiesta dell'esempio, o null per lasciarla
// passare (tutto quello che non riguarda l'upload 0 o i metadati).
export function demoResponse(request: Request): Response | null {
  if (!active) return null
  const { pathname } = new URL(request.url)
  const method = request.method.toUpperCase()
  const upload = UPLOAD.exec(pathname)
  if (upload) {
    const rest = upload[1] ?? ''
    if (method === 'DELETE') return json(null, 204)
    if (rest === '/episode-orders') {
      return json({ sources: {}, orders: [], recommended: null, files_order: null, fits: {}, warning: null, found: {} })
    }
    if (method === 'POST' && rest === '/match') {
      step = 'decision'
      emit()
    } else if (method === 'POST' && rest === '/approve') {
      step = 'approved'
      emit()
    }
    return json(job())
  }
  if (pathname.startsWith('/api/metadata/posters/')) return json({ detail: 'demo' }, 404)
  if (pathname === '/api/metadata/search') return json(demo.match.candidates.map((c) => ({ ...c, overview: null })))
  if (pathname.startsWith('/api/metadata/')) return json(demo.metadata)
  return null
}
