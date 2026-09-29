import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from '@/components/layout/AppLayout'
import { ComingSoon } from '@/pages/ComingSoon'
import { DashboardPage } from '@/pages/DashboardPage'
import { ConfigurationPage } from '@/pages/config/ConfigurationPage'
import { ReseedingPage } from '@/pages/reseeding/ReseedingPage'
import { WorkInProgress } from '@/pages/WorkInProgress'
import { FolderView } from '@/pages/library/FolderView'
import { LibraryDefaultView } from '@/pages/library/LibraryDefaultView'
import { PosterView } from '@/pages/library/PosterView'
import { NotImportedView } from '@/pages/torrent/NotImportedView'
import { TorrentFolderView } from '@/pages/torrent/TorrentFolderView'
import { t } from '@/lib/i18n'
import { NAV_DASHBOARD, NAV_GROUPS } from '@/lib/nav'

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
  '/torrent/not-imported': <NotImportedView />,
  '/reseeding': <ReseedingPage />,
  // Upload in lavorazione: le pagine (pages/upload) restano nel codice ma non
  // sono raggiungibili, per chi prova l'app. Ripristinare con UploadQueuePage
  // qui e NewUploadPage sulle due route sotto.
  '/upload': <WorkInProgress title="Upload" description={t('upload.workInProgress')} />,
  '/config': <ConfigurationPage />,
}

const RingLabPage = lazy(() => import('@/pages/lab/RingLabPage'))

const ALL_ITEMS = [NAV_DASHBOARD, ...NAV_GROUPS.flatMap((group) => group.items)]

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to={NAV_DASHBOARD.to} replace />} />
        <Route path="/library" element={<LibraryDefaultView />} />
        {/* Prototipo del logo (branch feature/ring-logo): fuori dalla navigazione,
            caricato a parte perché porta con sé Three.js. */}
        <Route
          path="/lab/ring"
          element={
            <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
              <RingLabPage />
            </Suspense>
          }
        />
        {ALL_ITEMS.map((item) => (
          <Route key={item.to} path={item.to} element={overrides[item.to] ?? <ComingSoon title={item.title} />} />
        ))}
        <Route path="/upload/*" element={<Navigate to="/upload" replace />} />
      </Route>
    </Routes>
  )
}

export default App
