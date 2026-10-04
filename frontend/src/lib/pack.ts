// Un pack di episodi scelti a mano (nazgarr/upload/pack.py): si selezionano i
// video nella libreria o nella vista dei torrent, e l'upload parte con quella
// lista invece di una cartella. I sottotitoli accanto agli episodi li
// aggiunge il backend.

import { useCallback, useMemo, useRef, useState } from 'react'

import type { UploadJob } from '@/api/hooks/uploads'

export interface PackFile {
  diskId: number
  path: string
}

export const packKey = (file: PackFile) => `${file.diskId}:${file.path}`

// Stesse estensioni di nazgarr/core/file_types.py.
const VIDEO_EXTENSIONS = ['.mkv', '.mp4', '.avi', '.m2ts', '.ts', '.wmv', '.mov']
export const isVideoPath = (path: string) => VIDEO_EXTENSIONS.some((ext) => path.toLowerCase().endsWith(ext))

// Perché la selezione non è ancora un pack, o null: almeno due video, tutti
// dello stesso disco (il torrent nasce dagli hardlink).
export function packProblem(files: PackFile[]): 'tooFew' | 'manyDisks' | null {
  if (files.length < 2) return 'tooFew'
  if (new Set(files.map((f) => f.diskId)).size > 1) return 'manyDisks'
  return null
}

export interface PackSelection {
  active: boolean
  setActive: (active: boolean) => void
  files: PackFile[]
  has: (file: PackFile) => boolean
  toggle: (file: PackFile) => void
  // Un clic su un video: con SHIFT anche tutti quelli fra lui e l'ultimo
  // cliccato, nell'ordine in cui la vista li mostra (ordered).
  pick: (file: PackFile, shift: boolean, ordered: PackFile[]) => void
  setMany: (files: PackFile[], on: boolean) => void
  clear: () => void
}

export function usePackSelection(): PackSelection {
  const [active, setActiveState] = useState(false)
  const [selected, setSelected] = useState<Map<string, PackFile>>(() => new Map())
  const setMany = useCallback((files: PackFile[], on: boolean) => {
    setSelected((prev) => {
      const next = new Map(prev)
      for (const file of files) {
        if (on) next.set(packKey(file), file)
        else next.delete(packKey(file))
      }
      return next
    })
  }, [])
  const toggle = useCallback(
    (file: PackFile) => setSelected((prev) => {
      const next = new Map(prev)
      if (next.has(packKey(file))) next.delete(packKey(file))
      else next.set(packKey(file), file)
      return next
    }),
    [],
  )
  const last = useRef<string | null>(null)
  const pick = useCallback(
    (file: PackFile, shift: boolean, ordered: PackFile[]) => {
      const keys = ordered.map(packKey)
      const from = last.current ? keys.indexOf(last.current) : -1
      const to = keys.indexOf(packKey(file))
      last.current = packKey(file)
      if (!shift || from < 0 || to < 0) {
        toggle(file)
        return
      }
      // Tutto l'intervallo prende lo stato che avrà il video cliccato.
      const on = !selected.has(packKey(file))
      setMany(ordered.slice(Math.min(from, to), Math.max(from, to) + 1), on)
    },
    [selected, setMany, toggle],
  )
  const clear = useCallback(() => setSelected(new Map()), [])
  const setActive = useCallback((on: boolean) => {
    setActiveState(on)
    last.current = null
    if (!on) setSelected(new Map())
  }, [])
  const files = useMemo(() => [...selected.values()].sort((a, b) => a.path.localeCompare(b.path)), [selected])
  return { active, setActive, files, has: (file) => selected.has(packKey(file)), toggle, pick, setMany, clear }
}

// La pagina del nuovo upload con il pack già scelto (nello state della
// navigazione: la lista può essere lunga per un URL).
export function packUploadTarget(files: PackFile[], tmdb?: string) {
  const params = new URLSearchParams()
  if (tmdb) params.set('tmdb', tmdb)
  const query = params.toString()
  return {
    to: `/upload/new${query ? `?${query}` : ''}`,
    state: { pack: { diskId: files[0]?.diskId, files: files.map((f) => f.path) } },
  }
}

export interface PackState {
  diskId: number
  files: string[]
}

export function readPackState(state: unknown): PackState | null {
  const pack = (state as { pack?: PackState } | null)?.pack
  if (!pack || typeof pack.diskId !== 'number' || !Array.isArray(pack.files) || pack.files.length === 0) return null
  return { diskId: pack.diskId, files: pack.files.filter((f) => typeof f === 'string') }
}

// I campi che cambiano fra gli episodi di un pack (analysis.pack_mixed), e la conferma dell'utente.
export function packMixed(job: UploadJob): Record<string, string[]> | null {
  const mixed = (job.analysis as { pack_mixed?: Record<string, string[]> } | null)?.pack_mixed
  return mixed && Object.keys(mixed).length > 0 ? mixed : null
}

export function packMixedConfirmed(job: UploadJob): boolean {
  return (job.overrides as Record<string, unknown>).pack_mixed_confirmed === true
}
