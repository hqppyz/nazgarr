import { uiLocale } from '@/lib/i18n'

// Formattazione del riepilogo MediaInfo (nazgarr/library/mediainfo.py summarize)
// come l'anteprima di un tracker UNIT3D.

export interface MediaInfoSummary {
  file_name: string | null
  general: { format: string | null; duration_ms: number | null; overall_bit_rate: number | null; file_size: number | null } | null
  video: {
    format: string | null
    format_profile: string | null
    bit_depth: number | null
    width: number | null
    height: number | null
    scan_type: string | null
    display_aspect_ratio: string | null
    frame_rate: string | null
    frame_rate_num: number | null
    frame_rate_den: number | null
    bit_rate: number | null
    hdr_format: string | null
    writing_library: string | null
  } | null
  audio: {
    language: string | null
    title: string | null
    format: string | null
    commercial_name: string | null
    channels: number | null
    channel_layout: string | null
    bit_rate: number | null
    default: boolean
  }[]
  subtitles: { language: string | null; title: string | null; format: string | null; forced: boolean }[]
}

// Lingua ISO 639 -> paese per la bandierina (l'inglese come negli USA,
// come fanno i tracker).
const FLAG_COUNTRY: Record<string, string> = {
  en: 'US', it: 'IT', fr: 'FR', de: 'DE', es: 'ES', pt: 'PT', ja: 'JP', ko: 'KR', zh: 'CN', ru: 'RU', nl: 'NL',
  sv: 'SE', da: 'DK', no: 'NO', nb: 'NO', fi: 'FI', pl: 'PL', cs: 'CZ', hu: 'HU', tr: 'TR', el: 'GR', he: 'IL',
  ar: 'SA', hi: 'IN', th: 'TH', uk: 'UA', ro: 'RO', bg: 'BG', hr: 'HR', sr: 'RS', sk: 'SK', sl: 'SI', et: 'EE',
  lv: 'LV', lt: 'LT', id: 'ID', ms: 'MY', vi: 'VN', fa: 'IR', ca: 'ES', is: 'IS',
}

export function flagOf(language: string | null | undefined): string | null {
  if (!language) return null
  const [lang, region] = language.toLowerCase().split(/[-_]/)
  const country = region && region.length === 2 ? region.toUpperCase() : FLAG_COUNTRY[lang]
  if (!country) return null
  return String.fromCodePoint(...[...country].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65))
}

const languageNames = new Intl.DisplayNames([uiLocale()], { type: 'language' })

export function languageName(language: string | null | undefined): string {
  if (!language) return 'Unknown'
  try {
    return languageNames.of(language) ?? language
  } catch {
    return language
  }
}

export function formatDuration(ms: number | null): string | null {
  if (!ms) return null
  const minutes = Math.round(ms / 60000)
  const hours = Math.floor(minutes / 60)
  return hours > 0 ? `${hours} h ${minutes % 60} min` : `${minutes} min`
}

export function formatBitrate(bps: number | null): string | null {
  if (!bps) return null
  return bps >= 1_000_000 ? `${(bps / 1_000_000).toFixed(1)}mb/s` : `${Math.round(bps / 1000)}kb/s`
}

// 6 canali con LFE -> 5.1ch, 2 -> 2.0ch, 8 -> 7.1ch.
export function formatChannels(channels: number | null, layout: string | null): string | null {
  if (!channels) return null
  const lfe = layout ? /LFE/.test(layout) : channels >= 6
  return lfe ? `${channels - 1}.1ch` : `${channels}.0ch`
}

export function formatFrameRate(video: NonNullable<MediaInfoSummary['video']>): string | null {
  if (!video.frame_rate) return null
  const exact = video.frame_rate_num && video.frame_rate_den && video.frame_rate_den !== 1
  return `${video.frame_rate}${exact ? ` (${video.frame_rate_num}/${video.frame_rate_den})` : ''} FPS`
}

export function audioLine(track: MediaInfoSummary['audio'][number]): string {
  return [
    languageName(track.language),
    track.commercial_name && track.commercial_name !== track.format ? track.commercial_name : track.format,
    formatChannels(track.channels, track.channel_layout),
    // L'audio sempre in kb/s, come nei tracker.
    track.bit_rate ? `${Math.round(track.bit_rate / 1000)}kb/s` : null,
    track.title,
  ]
    .filter(Boolean)
    .join(' / ')
}
