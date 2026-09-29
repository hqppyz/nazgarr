import { Outlet, useLocation } from 'react-router-dom'

import { useSetting } from '@/api/hooks/settings'

import { ActivityStack } from '@/components/ActivityStack'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { RunNowButton } from '@/components/RunNowButton'
import { RunStatusIndicator } from '@/components/RunStatusIndicator'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { setSizeUnits } from '@/lib/library-filters'
import { NAV_DASHBOARD, resolveSectionTitle } from '@/lib/nav'

function TopHeader() {
  const location = useLocation()
  const { parent, title } = resolveSectionTitle(location.pathname)

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
      <SidebarTrigger />
      <Separator orientation="vertical" className="h-4" />
      <div className="flex flex-1 items-center gap-1.5 text-sm">
        {parent && <span className="text-muted-foreground">{parent}</span>}
        {parent && <span className="text-muted-foreground">/</span>}
        <span className="font-medium">{title}</span>
      </div>
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
  return (
    <SidebarProvider className="h-svh">
      <AppSidebar />
      <SidebarInset className="h-svh overflow-hidden">
        <TopHeader />
        <div className="flex-1 overflow-auto p-6">
          <Outlet />
        </div>
      </SidebarInset>
      {/* In basso a destra, impilati: feedback delle azioni sopra, run sotto. */}
      <div className="fixed right-4 bottom-4 z-50 flex flex-col items-end gap-2">
        <ActivityStack />
        <RunStatusIndicator />
      </div>
    </SidebarProvider>
  )
}
