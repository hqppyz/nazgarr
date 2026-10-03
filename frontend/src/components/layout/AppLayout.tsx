import { useState } from 'react'
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
import { TourRunner } from '@/onboarding/TourRunner'
import { RemoteGate, RemotePill } from '@/components/instances/RemoteGate'
import { isRemote } from '@/lib/instance'
import { UploadNotices } from '@/components/upload/UploadNotices'
import { WelcomeDialog } from '@/onboarding/WelcomeDialog'

function TopHeader() {
  const location = useLocation()
  const { parent, title } = resolveSectionTitle(location.pathname)

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
      <SidebarTrigger />
      <div className="flex flex-1 items-center gap-1.5 text-sm">
        {parent && <span className="text-muted-foreground">{parent}</span>}
        {parent && <span className="text-muted-foreground">/</span>}
        <span className="font-medium">{title}</span>
      </div>
      <RemotePill />
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

export function AppLayout() {
  useSizeUnitsSync()
  const [floatingSlot, setFloatingSlot] = useState<HTMLElement | null>(null)
  return (
    <FloatingSlotContext.Provider value={floatingSlot}>
      <SidebarProvider className="h-svh">
        <AppSidebar />
        {/* Il tour è dell'istanza su cui si è fatto il login, non di quella che si guarda. */}
        {!isRemote() && <WelcomeDialog />}
        {!isRemote() && <TourRunner />}
        <UploadNotices />
        <SidebarInset className="h-svh overflow-hidden">
          <TopHeader />
          <div className="flex-1 overflow-auto p-4 md:p-6">
            <RemoteGate>
              <Outlet />
            </RemoteGate>
          </div>
        </SidebarInset>
        {/* In basso a destra, impilati: feedback delle azioni sopra, run sotto. */}
        <div className="fixed right-4 bottom-4 z-50 flex flex-col items-end gap-2">
          {/* Pannelli flottanti di una pagina (es. il registro di un upload). */}
          <div ref={setFloatingSlot} className="flex flex-col items-end gap-2 empty:hidden" />
          <ActivityStack />
          <RunStatusIndicator />
        </div>
      </SidebarProvider>
    </FloatingSlotContext.Provider>
  )
}
