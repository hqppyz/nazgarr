// Copia negli appunti anche fuori da HTTPS: navigator.clipboard esiste solo
// in un contesto sicuro, e Nazgarr gira spesso su http://ip:porta in LAN.
// from: l'elemento che ha chiesto la copia (il tasto), per il ripiego.
export async function copyText(text: string, from?: Element | null): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // ripiego sotto
    }
  }
  return copyWithSelection(text, from)
}

// Il ripiego: il testo in un campo nascosto, selezionato e copiato. Il campo
// va dentro il dialog del tasto, se c'è: un dialog tiene il focus al suo
// interno, e un campo fuori non si selezionerebbe (copia vuota).
function copyWithSelection(text: string, from?: Element | null): boolean {
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const anchor = from ?? active
  const container = anchor?.closest('[role="dialog"], [role="alertdialog"]') ?? document.body
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '') // niente tastiera sul telefono
  // 16px: Safari su iOS non zooma su un campo che riceve il focus.
  Object.assign(area.style, {
    position: 'fixed', top: '0', left: '0', width: '1px', height: '1px', padding: '0', border: '0',
    opacity: '0', fontSize: '16px',
  })
  container.appendChild(area)
  area.focus({ preventScroll: true })
  area.select()
  area.setSelectionRange(0, text.length) // iOS: select() da solo non seleziona
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
    active?.focus({ preventScroll: true })
  }
}
