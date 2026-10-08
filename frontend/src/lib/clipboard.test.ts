import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyText } from '@/lib/clipboard'

afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('copyText', () => {
  it('outside HTTPS selects the text inside the dialog of the button, then gives the focus back', async () => {
    vi.stubGlobal('isSecureContext', false)
    document.body.innerHTML = '<div role="dialog"><button>copy</button></div>'
    const button = document.querySelector('button')!
    button.focus()
    let seen: { text: string; inDialog: boolean } | null = null
    document.execCommand = vi.fn(() => {
      const field = document.activeElement as HTMLTextAreaElement
      seen = {
        text: field.value.slice(field.selectionStart, field.selectionEnd),
        inDialog: field.parentElement?.getAttribute('role') === 'dialog',
      }
      return true
    })

    expect(await copyText('nzg_secret', button)).toBe(true)

    expect(seen).toEqual({ text: 'nzg_secret', inDialog: true })
    expect(document.querySelector('textarea')).toBeNull()
    expect(document.activeElement).toBe(button)
  })

  it('says when the copy did not happen', async () => {
    vi.stubGlobal('isSecureContext', false)
    document.execCommand = vi.fn(() => false)

    expect(await copyText('x')).toBe(false)
  })
})
