import { useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { useSetting } from '@/api/hooks/settings'
import { FloatingSlotContext } from '@/lib/floatingSlot'

import { ActivityStack } from '@/components/ActivityStack'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { RunNowButton } from '@/components/RunNowButton'
import { RunStatusIndicator } from '@/components/RunStatusIndicator'
import { TrackerFilterSelect } from '@/components/TrackerFilterSelect'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { setSizeUnits } from '@/lib/library-filters'
import { NAV_DASHBOARD, resolveSectionTitle } from '@/lib/nav'
import { usesTrackerFilter } from '@/lib/trackerFilter'
import { RemoteBar, RemoteGate } from '@/components/instances/RemoteGate'
import { isRemote } from '@/lib/instance'
import { preloadPages } from '@/lib/lazyPages'
import { UploadNotices } from '@/components/upload/UploadNotices'
import { WelcomeDialog } from '@/onboarding/WelcomeDialog'

// Il tour (driver.js e il suo CSS) in un chunk a parte, fuori dal caricamento iniziale.
const TourRunner = lazy(() => import('@/onboarding/TourRunner').then((m) => ({ default: m.TourRunner })))

function TopHeader() {
  const location = useLocation()
  const { parent, title } = resolveSectionTitle(location.pathname)

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
      {/* Su telefono e tablet è l'unico modo di aprire il menu: più grande. */}
      <SidebarTrigger className="size-9 lg:size-7" />
      <div className="flex min-w-0 flex-1 items-center gap-1.5 text-sm">
        {parent && <span className="hidden text-muted-foreground sm:inline">{parent}</span>}
        {parent && <span className="hidden text-muted-foreground sm:inline">/</span>}
        <span className="truncate font-medium">{title}</span>
      </div>
      {usesTrackerFilter(location.pathname) && <TrackerFilterSelect />}
      {location.pathname === NAV_DASHBOARD.to && <RunNowButton />}
    </header>
  )
}

// Unità delle dimensioni scelte in Configuration > Interface:
// impostate prima che i figli vengano renderizzati, così ogni formatBytes le
// usa; al cambio dell'impostazione il layout si ridisegna e con lui le viste.
function useSizeUnitsSync() {
  const { data } = useSetting('size_units')
  setSizeUnits(data?.value === 'binary' ? 'binary' : 'decimal')
}

// Finita la pagina aperta (nessuna richiesta in corso), le altre pagine si
// scaricano in background: aprirle dopo è immediato.
function usePreloadPages() {
  const queryClient = useQueryClient()
  useEffect(() => preloadPages(() => queryClient.isFetching() > 0), [queryClient])
}

export function AppLayout() {
  useSizeUnitsSync()
  usePreloadPages()
  const [floatingSlot, setFloatingSlot] = useState<HTMLElement | null>(null)
  return (
    <FloatingSlotContext.Provider value={floatingSlot}>
      <SidebarProvider className="h-svh">
        <AppSidebar />
        {/* Il tour è dell'istanza su cui si è fatto il login, non di quella che si guarda. */}
        {!isRemote() && <WelcomeDialog />}
        {!isRemote() && (
          <Suspense fallback={null}>
            <TourRunner />
          </Suspense>
        )}
        <UploadNotices />
        <SidebarInset className="h-svh overflow-hidden">
          <TopHeader />
          <RemoteBar />
          {/* Sotto, spazio per i pannelli fissi in basso: sul telefono coprivano
              l'ultimo contenuto (es. il pulsante Approva di un upload). */}
          <div className="flex-1 overflow-auto p-4 pb-28 md:p-6 md:pb-28 lg:pb-6">
            <RemoteGate>
              <Outlet />
            </RemoteGate>
          </div>
        </SidebarInset>
        {/* In basso a destra, impilati: feedback delle azioni sopra, run sotto. */}
        {/* Sul telefono a tutta larghezza, e mai più alti dello schermo. */}
        <div className="fixed inset-x-4 bottom-4 z-50 flex max-h-[calc(100svh-6rem)] flex-col items-stretch gap-2 overflow-y-auto sm:inset-x-auto sm:right-4 sm:items-end">
          {/* Pannelli flottanti di una pagina (es. il registro di un upload). */}
          <div ref={setFloatingSlot} className="flex flex-col items-end gap-2 empty:hidden" />
          <ActivityStack />
          <RunStatusIndicator />
        </div>
      </SidebarProvider>
    </FloatingSlotContext.Provider>
  )
}
