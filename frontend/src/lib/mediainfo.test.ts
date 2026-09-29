import { describe, expect, it } from 'vitest'

import { audioLine, flagOf, formatBitrate, formatChannels, formatDuration } from '@/lib/mediainfo'

describe('mediainfo formatting', () => {
  it('formats like a tracker preview', () => {
    expect(formatDuration(6087000)).toBe('1 h 41 min')
    expect(formatBitrate(20_900_000)).toBe('20.9mb/s')
    expect(formatBitrate(640_000)).toBe('640kb/s')
    expect(formatChannels(6, 'L R C LFE Ls Rs')).toBe('5.1ch')
    expect(formatChannels(2, 'L R')).toBe('2.0ch')
    expect(audioLine({ language: 'en', title: 'Surround 5.1', format: 'MLP FBA', commercial_name: null, channels: 6,
      channel_layout: null, bit_rate: 1_541_000, default: true })).toBe('English / MLP FBA / 5.1ch / 1541kb/s / Surround 5.1')
  })

  it('maps languages to flags', () => {
    expect(flagOf('it')).toBe('🇮🇹')
    expect(flagOf('en')).toBe('🇺🇸')
    expect(flagOf('pt-BR')).toBe('🇧🇷')
    expect(flagOf('xx')).toBeNull()
  })
})
