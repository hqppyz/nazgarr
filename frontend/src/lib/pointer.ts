// Un popover che si apre al passaggio del mouse, ma non su touch: lì, su
// iOS, il tocco lo apriva (come passaggio) e lo richiudeva (come click)
// nello stesso momento. Sul touch si apre solo al tocco (2026-10-05).
export function opensOnHover(): boolean {
  return typeof window === 'undefined' || !window.matchMedia?.('(pointer: coarse)').matches
}
