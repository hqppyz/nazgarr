// Vista di default della libreria (Configuration > Interface): dove porta la
// voce "Library" della sidebar e la route /library. Folder se mai scelta.
export const LIBRARY_VIEW_SETTING = 'library_default_view'

export type LibraryView = 'folder' | 'poster'

export const LIBRARY_VIEW_PATHS: Record<LibraryView, string> = {
  folder: '/library/folder',
  poster: '/library/poster',
}

export function libraryViewOf(value: string | null | undefined): LibraryView {
  return value === 'poster' ? 'poster' : 'folder'
}
