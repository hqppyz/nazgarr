import { HardDriveDownloadIcon, RadioTowerIcon } from 'lucide-react'

import { AuthedImage } from '@/components/AuthedPoster'
import { cn } from '@/lib/utils'

// Loghi dei client in public/logos (homarr-labs/dashboard-icons e simili:
// marchi dei rispettivi proprietari, solo a scopo identificativo).
const CLIENT_LOGOS: Record<string, string> = {
  qbittorrent: '/logos/qbittorrent.svg',
  qui: '/logos/qui.svg',
  deluge: '/logos/deluge.svg',
  transmission: '/logos/transmission.svg',
  rutorrent: '/logos/rutorrent.svg',
  utorrent: '/logos/utorrent.svg',
  bittorrent: '/logos/bittorrent.svg',
}


// Liberi, senza riquadro, come i loghi di Radarr/Sonarr (components/ServiceLogo.tsx).
const BOX = 'size-8 shrink-0'

export function ClientLogo({ type }: { type: string }) {
  const logo = CLIENT_LOGOS[type]
  return (
    <div className={cn(BOX, 'flex items-center justify-center')}>
      {logo ? (
        <img src={logo} alt="" className="size-full object-contain" />
      ) : (
        <HardDriveDownloadIcon className="size-4 text-muted-foreground" />
      )}
    </div>
  )
}

// La favicon del tracker, scaricata dal backend (nazgarr/torrents/tracker_icons.py);
// senza, un'antenna generica.
export function TrackerLogo({ trackerId, className }: { trackerId: number; className?: string }) {
  return (
    <AuthedImage
      url={`/api/trackers/${trackerId}/icon`}
      className={className ?? BOX}
      fallback={<RadioTowerIcon className="size-4 text-muted-foreground" />}
    />
  )
}
