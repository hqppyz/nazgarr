import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { HostDescription } from '@/pages/config/ImageHostsCard'

describe('HostDescription', () => {
  it('links the site an image host description starts with', () => {
    render(<HostDescription description="https://lensdump.com (paid API)" />)
    expect(screen.getByRole('link').getAttribute('href')).toBe('https://lensdump.com/')
  })

  it('keeps a free sentence or another scheme as plain text', () => {
    const { rerender } = render(<HostDescription description="Screenshots on my own server" />)
    expect(screen.queryByRole('link')).toBeNull()
    rerender(<HostDescription description="file:///etc/passwd look here" />)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('file:///etc/passwd look here')).toBeTruthy()
  })
})
