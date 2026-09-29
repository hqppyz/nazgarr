import { cn } from '@/lib/utils'

// L'anello dorato del logo (stesso disegno di public/favicon.svg), inline
// per non dipendere da una richiesta in più.
export function RingLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={cn('size-6 shrink-0', className)} aria-hidden="true">
      <defs>
        <linearGradient id="ring-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff2b3" />
          <stop offset="0.35" stopColor="#f2c14e" />
          <stop offset="0.7" stopColor="#c9891a" />
          <stop offset="1" stopColor="#8a5a0b" />
        </linearGradient>
        <linearGradient id="ring-inner" x1="1" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#7a4d08" />
          <stop offset="1" stopColor="#e0a93a" />
        </linearGradient>
      </defs>
      <ellipse cx="32" cy="32" rx="26" ry="22" fill="none" stroke="url(#ring-gold)" strokeWidth="9" />
      <ellipse cx="32" cy="32" rx="21.5" ry="17.5" fill="none" stroke="url(#ring-inner)" strokeWidth="1.5" opacity="0.8" />
      <path d="M14 22 A26 22 0 0 1 30 10.5" fill="none" stroke="#fffbe6" strokeWidth="2.2" strokeLinecap="round" opacity="0.85" />
    </svg>
  )
}
