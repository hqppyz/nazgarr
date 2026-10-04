// Il modulo di un'istanza Radarr/Sonarr (Configurazione › Integrazioni),
// aggiunta o modificata: i campi e i corpi delle richieste.

export type ArrInstanceForm = {
  label: string
  baseUrl: string
  apiKey: string
  priority: string
  timeoutSeconds: string
  basicAuth: boolean
  basicAuthUsername: string
  basicAuthPassword: string
}

export function emptyArrForm(instance?: {
  label: string
  base_url: string
  priority: number
  timeout_seconds: number
  basic_auth_username: string | null
}): ArrInstanceForm {
  return {
    label: instance?.label ?? '',
    baseUrl: instance?.base_url ?? '',
    apiKey: '',
    priority: String(instance?.priority ?? 0),
    timeoutSeconds: String(instance?.timeout_seconds ?? 15),
    basicAuth: instance != null && instance.basic_auth_username !== null,
    basicAuthUsername: instance?.basic_auth_username ?? '',
    basicAuthPassword: '',
  }
}

// Creando, la basic auth si manda solo se accesa. Modificando: una API key o
// una password vuota restano quelle salvate; la basic auth spenta si cancella
// (username vuoto, nazgarr/api/arr_instances.py).
export function arrInstanceBody(form: ArrInstanceForm, editing: boolean) {
  const common = {
    label: form.label,
    base_url: form.baseUrl,
    priority: Number(form.priority) || 0,
    timeout_seconds: Number(form.timeoutSeconds) || 15,
  }
  if (!editing) {
    return {
      ...common,
      api_key: form.apiKey,
      basic_auth_username: form.basicAuth ? form.basicAuthUsername : undefined,
      basic_auth_password: form.basicAuth ? form.basicAuthPassword : undefined,
    }
  }
  return {
    ...common,
    api_key: form.apiKey || undefined,
    basic_auth_username: form.basicAuth ? form.basicAuthUsername : '',
    basic_auth_password: form.basicAuth && form.basicAuthPassword ? form.basicAuthPassword : undefined,
  }
}

// La prova con i valori del modulo (prima di salvare, o con una nuova API key).
export function arrConnectionBody(form: ArrInstanceForm) {
  return {
    base_url: form.baseUrl,
    api_key: form.apiKey,
    timeout_seconds: Number(form.timeoutSeconds) || 15,
    basic_auth_username: form.basicAuth ? form.basicAuthUsername : undefined,
    basic_auth_password: form.basicAuth ? form.basicAuthPassword : undefined,
  }
}
