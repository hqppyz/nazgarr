import {
  FolderTree,
  Gauge,
  HardDriveDownload,
  LayoutDashboard,
  Settings,
  UploadCloud,
  type LucideIcon,
} from 'lucide-react'

// Struttura di navigazione da docs/SPEC.md §10, con aggiustamenti su
// richiesta esplicita dell'utente:
// - Dashboard promossa a voce di primo livello (non più sotto Reseeding):
//   dà una panoramica sull'intero stato dell'app (libreria, reseeding,
//   upload), non solo sul reseeding.
// - Un gruppo con una sola voce si mostra come link piatto (icona +
//   titolo del gruppo, nessun dropdown) — vedi AppSidebar.tsx. Library è
//   l'unico gruppo con più voci: non si espande, è un link alla vista di
//   default (Configuration > Interface) con Folder/Poster sempre sotto.
// "Verify from .torrent" e "Description templates" restano deliberatamente
// fuori da questa fase (vedi piano Fase 8): il primo non ha ancora un
// endpoint API dedicato, il secondo è già raggiungibile editando il
// profilo di upload di un tracker (Configuration > Integrations).
export interface NavItem {
  title: string
  to: string
  // Etichetta accanto alla voce nella sidebar, es. "WIP" per una sezione
  // non ancora pronta.
  badge?: string
}

export interface NavGroup {
  title: string
  icon: LucideIcon
  items: NavItem[]
  // Il gruppo è esso stesso un link (non un menu che si espande), con le
  // voci sempre visibili sotto. Library: /library apre la vista di default
  // scelta in Configuration > Interface.
  to?: string
}

export interface NavLink {
  title: string
  to: string
  icon: LucideIcon
}

export const NAV_DASHBOARD: NavLink = { title: 'Dashboard', to: '/dashboard', icon: LayoutDashboard }

export const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Library',
    icon: FolderTree,
    to: '/library',
    items: [
      { title: 'Folder view', to: '/library/folder' },
      { title: 'Poster view', to: '/library/poster' },
    ],
  },
  {
    title: 'Torrent',
    icon: HardDriveDownload,
    to: '/torrent/folder',
    items: [
      { title: 'Files', to: '/torrent/folder' },
      { title: 'Not imported', to: '/torrent/not-imported' },
    ],
  },
  {
    title: 'Reseeding',
    icon: Gauge,
    items: [{ title: 'Reseeding', to: '/reseeding' }],
  },
  {
    title: 'Upload',
    icon: UploadCloud,
    items: [{ title: 'Upload', to: '/upload', badge: 'WIP' }],
  },
  {
    title: 'Configuration',
    icon: Settings,
    items: [{ title: 'Configuration', to: '/config' }],
  },
]

export interface SectionTitle {
  parent?: string
  title: string
}

// Titolo della sezione corrente mostrato nella topbar della main view
// (icona per collassare la sidebar + titolo), su tutte le pagine e non
// solo sulla Dashboard. Per i gruppi con più voci (solo Library, vedi
// sopra) mostra anche il genitore come breadcrumb ("Library / Poster view").
export function resolveSectionTitle(pathname: string): SectionTitle {
  if (pathname === NAV_DASHBOARD.to) return { title: NAV_DASHBOARD.title }
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (pathname === item.to || pathname.startsWith(`${item.to}/`)) {
        return group.items.length === 1 ? { title: group.title } : { parent: group.title, title: item.title }
      }
    }
  }
  return { title: NAV_DASHBOARD.title }
}
