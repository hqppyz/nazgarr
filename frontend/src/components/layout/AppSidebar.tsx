import { LogOutIcon, PaletteIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { useDashboard } from '@/api/hooks/dashboard'
import { useHealth } from '@/api/hooks/health'
import { RingLogo } from '@/components/RingLogo'
import { InstanceSwitcher } from '@/components/instances/InstanceSwitcher'
import type { RingHandle } from '@/components/ring/types'
import { Button, buttonVariants } from '@/components/ui/button'
import { useAuth } from '@/contexts/AuthContext'
import { t } from '@/lib/i18n'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar'
import { cn } from '@/lib/utils'
import { NAV_DASHBOARD, NAV_GROUPS } from '@/lib/nav'
import { parseApiDate } from '@/lib/time'

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return t('layout.timeNever')
  const minutes = Math.round((Date.now() - parseApiDate(iso).getTime()) / 60_000)
  if (minutes < 1) return t('layout.timeNow')
  if (minutes < 60) return t('layout.timeMinutesAgo', { minutes })
  const hours = Math.round(minutes / 60)
  if (hours < 24) return t('layout.timeHoursAgo', { hours })
  return t('layout.timeDaysAgo', { days: Math.round(hours / 24) })
}

function StatBox({ dotClassName, label, value }: { dotClassName: string; label: string; value: string }) {
  return (
    <div className="rounded-md border bg-sidebar-accent/40 px-2 py-1.5">
      <div className="flex items-center gap-1.5">
        <span className={cn('size-1.5 shrink-0 rounded-full', dotClassName)} />
        <span className="truncate text-[11px] font-medium text-muted-foreground">{label}</span>
      </div>
      <p className="mt-0.5 font-mono text-sm font-semibold">{value}</p>
    </div>
  )
}

// Ispirato al footer sidebar di Auditorr (progetto di provenienza, vedi
// docs/SPEC.md §0): due box di statistiche affiancati + orario
// dell'ultima scansione, sempre visibili senza dover aprire la
// Dashboard. Auditorr non mostra una versione in UI; qui aggiunta su
// richiesta esplicita (GET /api/health, nazgarr/core/version.py).
const COPYRIGHT_YEAR = new Date().getFullYear()

function AppSidebarFooter() {
  const { data: dashboard } = useDashboard()
  const { data: health } = useHealth()
  const { username, logout } = useAuth()

  return (
    <SidebarFooter className="gap-2 border-t px-3 py-3 group-data-[collapsible=icon]:hidden">
      <div className="grid grid-cols-2 gap-1.5">
        <StatBox
          dotClassName="bg-emerald-500"
          label={t('layout.health')}
          value={dashboard?.total_media_size ? `${Math.round(dashboard.health_pct)}/100` : '—'}
        />
        <StatBox
          dotClassName="bg-amber-500"
          label={t('layout.toReview')}
          value={dashboard ? String(dashboard.pending_review) : '—'}
        />
      </div>
      <p className="font-mono text-[11px] text-muted-foreground">
        {t('layout.lastRun', { time: relativeTime(dashboard?.last_run?.finished_at) })}
      </p>
      {/* Versione e copyright a sinistra, tema (Interface) e logout a destra. */}
      <div className="mt-1 flex items-center justify-between gap-2">
        <div className="grid min-w-0 gap-0.5 text-xs text-muted-foreground">
          <span className="truncate font-medium" title={health?.commit ? `commit ${health.commit}` : undefined}>
            {t('layout.version', { version: health?.version ?? '…' })}
          </span>
          <span className="truncate">© {COPYRIGHT_YEAR} lktorrentz</span>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Link
            to="/config?tab=interface"
            title={t('layout.themeSettings')}
            aria-label={t('layout.themeSettings')}
            className={buttonVariants({ variant: 'ghost', size: 'icon-sm' })}
          >
            <PaletteIcon className="size-4" />
          </Link>
          {username && (
            <Button variant="ghost" size="icon-sm" title={t('layout.logout', { username })}
                    aria-label={t('layout.logout', { username })} onClick={logout}>
              <LogOutIcon className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </SidebarFooter>
  )
}

// Lampo di luce quando la sidebar si apre o si chiude.
function SidebarRing() {
  const { state } = useSidebar()
  const ring = useRef<RingHandle>(null)
  const previous = useRef(state)
  useEffect(() => {
    if (previous.current !== state) ring.current?.collapse(state === 'collapsed')
    previous.current = state
  }, [state])
  return <RingLogo size={32} handleRef={ring} />
}

export function AppSidebar() {
  const location = useLocation()
  // Sul telefono il menu è un pannello sopra la pagina: toccata una voce si
  // chiude, se no si navigava dietro il pannello ancora aperto.
  const { isMobile, setOpenMobile } = useSidebar()
  useEffect(() => {
    if (isMobile) setOpenMobile(false)
  }, [location.pathname, location.search]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Sidebar collapsible="icon">
      {/* L'anello resta visibile anche a sidebar chiusa; sparisce solo il nome.
          Stesso margine sinistro aperta e chiusa (8px: nella barra chiusa da
          48px un anello da 32px resta centrato), così non si sposta. */}
      <SidebarHeader className="px-2 py-3">
        <span className="flex items-center gap-2">
          <SidebarRing />
          {/* Con altre istanze, sotto il nome quella che si sta guardando (components/instances). */}
          <span className="grid min-w-0 gap-0.5 group-data-[collapsible=icon]:hidden">
            <span className="truncate text-base leading-tight font-semibold tracking-tight">Nazgarr</span>
            <InstanceSwitcher />
          </span>
        </span>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="px-2 py-0.5">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  render={<Link to={NAV_DASHBOARD.to} />}
                  isActive={location.pathname === NAV_DASHBOARD.to}
                  tooltip={NAV_DASHBOARD.title}
                >
                  <NAV_DASHBOARD.icon className="size-4" />
                  {NAV_DASHBOARD.title}
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {NAV_GROUPS.map((group) => {
          // Ogni gruppo è una voce sola, come Dashboard: link piatto con icona e
          // titolo, evidenziato anche sulle sue viste e sotto-route (es.
          // /library/poster, /upload/123). Le viste di Library e Torrent si
          // scelgono in cima alla pagina.
          const isActive = group.items.some(
            (item) => location.pathname === item.to || location.pathname.startsWith(`${item.to}/`),
          )
          const badge = group.items.length === 1 ? group.items[0].badge : undefined
          return (
            <SidebarGroup key={group.title} className="px-2 py-0.5">
              <SidebarGroupContent>
                <SidebarMenu>
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      render={<Link to={group.to ?? group.items[0].to} />}
                      isActive={isActive}
                      tooltip={group.title}
                    >
                      <group.icon className="size-4" />
                      {group.title}
                    </SidebarMenuButton>
                    {badge && (
                      <SidebarMenuBadge className="font-mono text-[length:var(--text-xxs)] text-muted-foreground">
                        {badge}
                      </SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )
        })}
      </SidebarContent>
      <AppSidebarFooter />
      <SidebarRail />
    </Sidebar>
  )
}
