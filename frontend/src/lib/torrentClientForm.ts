// Il modulo di un client torrent (Configurazione › Client), aggiunto o
// modificato: i campi e il corpo della richiesta.

// La Web UI di Deluge ha solo la password.
export const PASSWORD_ONLY = new Set(['deluge'])

// I campi del dialogo di un client, aggiunto o modificato.
export type TorrentClientForm = {
  label: string
  adapterType: string
  baseUrl: string
  username: string
  password: string
  apiToken: string
  quiInstanceId: string
}

// Il corpo della richiesta: per tipo, solo le credenziali che quel client usa
// (qui: API key e istanza; Deluge: solo la password; un plugin: i suoi campi).
// Un segreto vuoto non si manda: in modifica vuol dire "mantieni quello salvato".
export function torrentClientPayload(form: TorrentClientForm, pluginConfig?: Record<string, unknown>) {
  const isQui = form.adapterType === 'qui'
  const passwordOnly = PASSWORD_ONLY.has(form.adapterType)
  if (pluginConfig) {
    return { label: form.label, base_url: form.baseUrl, config: pluginConfig }
  }
  return {
    label: form.label,
    base_url: form.baseUrl,
    username: isQui || passwordOnly ? undefined : form.username || undefined,
    password: isQui ? undefined : form.password || undefined,
    api_token: isQui ? form.apiToken || undefined : undefined,
    qui_instance_id: isQui && form.quiInstanceId ? Number(form.quiInstanceId) : undefined,
  }
}
