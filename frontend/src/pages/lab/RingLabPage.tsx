import { ChevronsLeftIcon, ChevronsRightIcon, FlameIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { RING_STATIC_SRC } from '@/components/RingLogo'
import type { RingHandle } from '@/components/ring/types'
import { WebGLRing } from '@/components/ring/WebGLRing'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

// Pagina di prova del logo (route /lab/ring, fuori dalla navigazione, e
// /ring-lab.html in sviluppo): l'anello in grande, alle misure della sidebar,
// in una sidebar finta, e accanto l'immagine statica usata come ripiego.
// Parametri: ?solo (solo l'anello grande), ?glow (acceso), ?export (usato da
// scripts/render-ring.mjs per generare public/ring.png).

const params = () => new URLSearchParams(window.location.search)
const EXPORT_SIZE = 256

function MockSidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const ring = useRef<RingHandle>(null)
  const toggle = () => {
    ring.current?.collapse(!collapsed)
    setCollapsed(!collapsed)
  }
  return (
    <div className="flex h-44 overflow-hidden rounded-lg border bg-background">
      <div className={cn('flex flex-col border-r bg-sidebar transition-[width] duration-700 ease-in-out', collapsed ? 'w-12' : 'w-64')}>
        <div className={cn('flex items-center gap-2 py-3', collapsed ? 'justify-center px-0' : 'px-3')}>
          <WebGLRing size={28} handleRef={ring} />
          {!collapsed && <span className="truncate text-base font-semibold tracking-tight">Nazgarr</span>}
        </div>
        <div className="grid gap-1.5 px-3">
          {[60, 45, 70].map((w) => (
            <div key={w} className={cn('h-2 rounded bg-muted', collapsed && 'mx-auto w-5')} style={collapsed ? undefined : { width: `${w}%` }} />
          ))}
        </div>
      </div>
      <div className="flex flex-1 items-start p-3">
        <Button variant="outline" size="sm" onClick={toggle}>
          {collapsed ? <ChevronsRightIcon className="size-4" /> : <ChevronsLeftIcon className="size-4" />}
          {collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        </Button>
      </div>
    </div>
  )
}

function SoloRing() {
  const ring = useRef<RingHandle>(null)
  useEffect(() => {
    if (params().has('glow')) ring.current?.glow(true, true)
  }, [])
  return (
    <div className="flex min-h-[80vh] items-center justify-center">
      <WebGLRing size={560} handleRef={ring} />
    </div>
  )
}

// Un solo fotogramma, fermo, con lo sfondo trasparente: il PNG finisce in un
// <img id="ring-export"> da cui lo legge scripts/render-ring.mjs.
function ExportRing() {
  const [data, setData] = useState<string | null>(null)
  return (
    <div>
      <WebGLRing size={EXPORT_SIZE} hoverable={false} onRendered={(canvas) => setData(canvas.toDataURL('image/png'))} />
      {data && <img id="ring-export" src={data} alt="" />}
    </div>
  )
}

function Lab() {
  const big = useRef<RingHandle>(null)
  const [lit, setLit] = useState(() => params().has('glow'))
  useEffect(() => {
    if (lit) big.current?.glow(true, true)
    // solo al primo render: poi comanda il pulsante
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <div className="grid gap-6">
      <div className="grid gap-1">
        <h1 className="text-lg font-semibold">Ring logo lab</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          The sidebar logo: a 3D ring in WebGL (Three.js, animated with GSAP) with the full inscription in an invented
          fantasy script. Next to it, the static image used when motion is reduced or WebGL isn't available
          (regenerate it with <code>npm run render:ring</code>).
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>WebGL ring</CardTitle>
          <CardDescription>Hover the ring: the inscription lights up and the ring leans toward the cursor.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <div className="grid gap-4 md:grid-cols-[1fr_auto]">
            <div className="flex items-center justify-center rounded-lg border bg-gradient-to-b from-muted/40 to-background py-6">
              <WebGLRing size={240} handleRef={big} />
            </div>
            <div className="grid content-center justify-items-center gap-2 rounded-lg border px-6 py-4">
              <img src={RING_STATIC_SRC} width={120} height={120} alt="" />
              <span className="text-xs text-muted-foreground">Static fallback</span>
            </div>
          </div>
          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                big.current?.glow(!lit)
                setLit(!lit)
              }}
            >
              <FlameIcon className="size-4" />
              {lit ? 'Dim' : 'Light up'}
            </Button>
          </div>
          <div className="grid gap-2">
            <p className="text-xs font-medium text-muted-foreground">Sidebar sizes (hover each)</p>
            <div className="flex items-end gap-6">
              {[24, 28, 36, 48, 64].map((size) => (
                <div key={size} className="grid justify-items-center gap-1">
                  <WebGLRing size={size} />
                  <span className="font-mono text-[length:var(--text-xxs)] text-muted-foreground">{size}px</span>
                </div>
              ))}
            </div>
          </div>
          <div className="grid gap-2">
            <p className="text-xs font-medium text-muted-foreground">In the sidebar, open and collapsed</p>
            <MockSidebar />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default function RingLabPage() {
  if (params().has('export')) return <ExportRing />
  if (params().has('solo')) return <SoloRing />
  return <Lab />
}
