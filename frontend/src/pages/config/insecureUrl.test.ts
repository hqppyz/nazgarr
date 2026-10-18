import { describe, expect, it } from 'vitest'

import { insecureUrlWarning, plainHttpToPublicHost } from '@/pages/config/insecureUrl'

describe('plainHttpToPublicHost', () => {
  it('warns about plain http to what looks like a public address', () => {
    for (const url of ['http://tracker.example', 'http://93.184.216.34:8080', 'http://seedbox.example.com:8080/']) {
      expect(plainHttpToPublicHost(url)).toBe(true)
    }
  })

  it('does not warn for https, the LAN, loopback, Tailscale or local names', () => {
    for (const url of [
      'https://tracker.example', 'http://192.168.1.10:8080', 'http://10.0.0.5', 'http://172.20.0.3:7878',
      'http://127.0.0.1:9091', 'http://100.101.102.103', 'http://localhost:8080', 'http://qbittorrent:8080',
      'http://nas.lan:8080', 'http://box.tail1234.ts.net', 'http://[::1]:8080', 'http://[fd00::5]', 'not a url', '',
    ]) {
      expect(plainHttpToPublicHost(url), url).toBe(false)
    }
  })
})

describe('insecureUrlWarning', () => {
  it("follows the server's verdict while the address is the saved one", () => {
    const saved = { base_url: 'http://seedbox.local.example', insecure_public_url: false }
    expect(insecureUrlWarning('http://seedbox.local.example', saved)).toBe(false)
    expect(insecureUrlWarning('http://other.example', saved)).toBe(true)
    expect(insecureUrlWarning('http://qbit:8080', { base_url: 'http://qbit:8080', insecure_public_url: true })).toBe(true)
  })
})
