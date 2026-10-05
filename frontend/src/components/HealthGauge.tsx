import { cn } from '@/lib/utils'

// Anello da 270° (apertura in basso), come il gauge di Auditorr: traccia
// grigia e arco del valore, disegnati in SVG senza librerie.
const RADIUS = 80
const STROKE = 18
const SWEEP = 270
const CIRCUMFERENCE = 2 * Math.PI * RADIUS
const ARC = (CIRCUMFERENCE * SWEEP) / 360

export function HealthGauge({
  value,
  color,
  className,
  children,
}: {
  value: number
  color?: string // colore della fascia di salute; di default il colore primario
  className?: string
  children?: React.ReactNode
}) {
  const clamped = Math.max(0, Math.min(100, value))
  const size = 2 * (RADIUS + STROKE)
  // Parte da in basso a sinistra (135°) e gira in senso orario.
  const circle = {
    cx: size / 2, cy: size / 2, r: RADIUS, fill: 'none', strokeWidth: STROKE, strokeLinecap: 'round' as const,
    transform: `rotate(135 ${size / 2} ${size / 2})`,
  }
  return (
    <div className={cn('relative mx-auto aspect-square w-40 max-w-full sm:w-52', className)}>
      <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full" role="img" aria-label={`${clamped.toFixed(0)} / 100`}>
        <circle {...circle} className="stroke-muted" strokeDasharray={`${ARC} ${CIRCUMFERENCE}`} />
        <circle
          {...circle}
          className={cn('transition-[stroke-dasharray] duration-700', !color && 'stroke-primary')}
          style={color ? { stroke: color } : undefined}
          strokeDasharray={`${(ARC * clamped) / 100} ${CIRCUMFERENCE}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">{children}</div>
    </div>
  )
}
