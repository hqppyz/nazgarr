import { afterEach, describe, expect, it } from 'vitest'

import { activeInstanceId, instancePath } from '@/lib/instance'

afterEach(() => window.localStorage.clear())

describe('the instance being viewed', () => {
  it('sends every API call through the proxy of this instance, except login and the instances', () => {
    expect(instancePath('/api/disks?x=1', 3)).toBe('/api/remote/3/api/disks?x=1')
    expect(instancePath('/api/library/posters/tv/1.jpg', 3)).toBe('/api/remote/3/api/library/posters/tv/1.jpg')
    for (const local of ['/api/auth/login', '/api/instances', '/api/instances/3/test', '/api/remote/3/api/disks']) {
      expect(instancePath(local, 3)).toBe(local)
    }
    expect(instancePath('/api/disks', null)).toBe('/api/disks')
    expect(instancePath('/assets/x.js', 3)).toBe('/assets/x.js')
  })

  it('remembers the choice in the browser', () => {
    expect(activeInstanceId()).toBeNull()
    window.localStorage.setItem('nazgarr-instance', '4')
    expect(activeInstanceId()).toBe(4)
    window.localStorage.setItem('nazgarr-instance', 'garbage')
    expect(activeInstanceId()).toBeNull()
  })
})
