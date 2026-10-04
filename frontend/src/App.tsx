import { type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from '@/components/layout/AppLayout'
import { ComingSoon } from '@/pages/ComingSoon'
import { lazyPage } from '@/lib/lazyPages'
import { NAV_DASHBOARD, NAV_GROUPS } from '@/lib/nav'

// Ogni pagina è un chunk a parte (src/lib/lazyPages.tsx): il bundle iniziale
// non porta con sé grafici (recharts), drag and drop (dnd-kit),
// configurazione e upload di chi apre solo la dashboard; le altre pagine si
// scaricano in background subito dopo.
const DashboardPage = lazyPage(() => import('@/pages/DashboardPage'), (m) => m.DashboardPage)
const PosterView = lazyPage(() => import('@/pages/library/PosterView'), (m) => m.PosterView)
const FolderView = lazyPage(() => import('@/pages/library/FolderView'), (m) => m.FolderView)
const LibraryDefaultView = lazyPage(() => import('@/pages/library/LibraryDefaultView'), (m) => m.LibraryDefaultView)
const TorrentFolderView = lazyPage(() => import('@/pages/torrent/TorrentFolderView'), (m) => m.TorrentFolderView)
const NotImportedView = lazyPage(() => import('@/pages/torrent/NotImportedView'), (m) => m.NotImportedView)
const ReseedingPage = lazyPage(() => import('@/pages/reseeding/ReseedingPage'), (m) => m.ReseedingPage)
const UploadQueuePage = lazyPage(() => import('@/pages/upload/UploadQueuePage'), (m) => m.UploadQueuePage)
const NewUploadPage = lazyPage(() => import('@/pages/upload/NewUploadPage'), (m) => m.NewUploadPage)
const UploadJobPage = lazyPage(() => import('@/pages/upload/UploadJobPage'), (m) => m.UploadJobPage)
const ConfigurationPage = lazyPage(() => import('@/pages/config/ConfigurationPage'), (m) => m.ConfigurationPage)
const InstancesPage = lazyPage(() => import('@/pages/InstancesPage'), (m) => m.InstancesPage)
// Il laboratorio del logo porta Three.js: mai precaricato.
const RingLabPage = lazyPage(() => import('@/pages/lab/RingLabPage'), (m) => m.default, { preload: false })

// Ogni voce di navigazione (NAV_DASHBOARD + NAV_GROUPS) diventa una route:
// ComingSoon di default, sostituita da una pagina reale via `overrides`
// man mano che le sotto-fasi della Fase 8 la implementano (vedi il
// piano). Un solo posto dove aggiungere una nuova pagina reale, mai due
// elenchi di route da tenere sincronizzati a mano.
const overrides: Record<string, ReactNode> = {
  [NAV_DASHBOARD.to]: <DashboardPage />,
  '/library/poster': <PosterView />,
  '/library/folder': <FolderView />,
  '/torrent/folder': <TorrentFolderView />,
  '/torrent/triage': <NotImportedView />,
  '/reseeding': <ReseedingPage />,
  '/upload': <UploadQueuePage />,
  '/config': <ConfigurationPage />,
}

const ALL_ITEMS = [NAV_DASHBOARD, ...NAV_GROUPS.flatMap((group) => group.items)]

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to={NAV_DASHBOARD.to} replace />} />
        <Route path="/library" element={<LibraryDefaultView />} />
        {/* "Non importati" è diventato Triage: i link salvati arrivano lì. */}
        <Route path="/torrent/not-imported" element={<Navigate to="/torrent/triage" replace />} />
        {/* Prototipo del logo (branch feature/ring-logo): fuori dalla navigazione,
            caricato a parte perché porta con sé Three.js. */}
        <Route path="/lab/ring" element={<RingLabPage />} />
        {ALL_ITEMS.map((item) => (
          <Route key={item.to} path={item.to} element={overrides[item.to] ?? <ComingSoon title={item.title} />} />
        ))}
        <Route path="/instances" element={<InstancesPage />} />
        <Route path="/upload/new" element={<NewUploadPage />} />
        <Route path="/upload/:uploadId" element={<UploadJobPage />} />
      </Route>
    </Routes>
  )
}

export default App
