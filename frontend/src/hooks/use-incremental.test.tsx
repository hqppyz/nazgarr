import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useIncrementalCount } from '@/hooks/use-incremental'

class FakeObserver {
  static all: FakeObserver[] = []
  readonly callback: IntersectionObserverCallback
  readonly root: Element | Document | null
  readonly rootMargin: string
  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.callback = callback
    this.root = options?.root ?? null
    this.rootMargin = options?.rootMargin ?? ''
    FakeObserver.all.push(this)
  }
  observe() {}
  disconnect() {
    FakeObserver.all = FakeObserver.all.filter((o) => o !== this)
  }
}

function Rows({ total }: { total: number }) {
  const { visible, hasMore, sentinelRef } = useIncrementalCount<HTMLTableRowElement>(total, 2, 'all')
  return (
    <table>
      <tbody>
        {Array.from({ length: visible }, (_, i) => (
          <tr key={i} data-row>
            <td>{i}</td>
          </tr>
        ))}
        {hasMore && <tr ref={sentinelRef} />}
      </tbody>
    </table>
  )
}

describe('useIncrementalCount', () => {
  const original = globalThis.IntersectionObserver
  beforeEach(() => {
    FakeObserver.all = []
    globalThis.IntersectionObserver = FakeObserver as unknown as typeof IntersectionObserver
  })
  afterEach(() => {
    globalThis.IntersectionObserver = original
  })

  it("watches the sentinel against the page's scrolling area, past a table's own wrapper", () => {
    const { container } = render(
      <div data-scroll-root>
        <div className="overflow-x-auto">
          <Rows total={5} />
        </div>
      </div>,
    )
    expect(container.querySelectorAll('[data-row]')).toHaveLength(2)
    expect(FakeObserver.all.map((o) => [o.root, o.rootMargin])).toEqual([[container.querySelector('[data-scroll-root]'), '800px']])

    act(() => FakeObserver.all[0].callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver))
    expect(container.querySelectorAll('[data-row]')).toHaveLength(4)
  })

  it('watches a sentinel that mounts after the rows were counted (the list behind the ring loader)', () => {
    // NotImportedView: i dati arrivano mentre il loader sfuma, la tabella
    // (e la sentinella) monta dopo, senza che count o total cambino.
    function Late({ total, shown }: { total: number; shown: boolean }) {
      const { visible, hasMore, sentinelRef } = useIncrementalCount<HTMLDivElement>(total, 2, 'all')
      if (!shown) return <p>loading</p>
      return (
        <div>
          {Array.from({ length: visible }, (_, i) => (
            <p key={i} data-row>
              {i}
            </p>
          ))}
          {hasMore && <div ref={sentinelRef} />}
        </div>
      )
    }
    const { container, rerender } = render(<Late total={0} shown={false} />)
    rerender(<Late total={5} shown={false} />)
    expect(FakeObserver.all).toHaveLength(0)
    rerender(<Late total={5} shown />)
    expect(container.querySelectorAll('[data-row]')).toHaveLength(2)
    expect(FakeObserver.all).toHaveLength(1)

    act(() => FakeObserver.all[0].callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver))
    expect(container.querySelectorAll('[data-row]')).toHaveLength(4)
  })

  it('falls back to the window outside the scrolling area (a sheet, a dialog)', () => {
    render(<Rows total={5} />)
    expect(FakeObserver.all.map((o) => o.root)).toEqual([null])
  })
})
