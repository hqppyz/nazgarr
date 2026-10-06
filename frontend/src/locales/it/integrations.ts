export const integrations = {
  'integrations.arrUsageDescription':
    'Sola lettura. A ogni scansione, i file che queste istanze conoscono vengono identificati senza una ricerca su TMDB, e i file orfani vengono associati al torrent da cui sono stati importati (dalla cronologia) senza cercare sul tracker. I file si associano per cartella, nome del file e dimensione esatta, quindi non serve nessuna mappatura dei percorsi.',
  'integrations.autoApproveThresholdsTitle': 'Soglie di raccomandazione',
  'integrations.rematchTitle': 'Frequenza di ricerca sui tracker',
  'integrations.rematchDescription':
    'Un file orfano già cercato su un tracker non viene ricercato a ogni scansione: candidati e proposta restano come sono finché il file non cambia o non passa questo intervallo. Così le scansioni non sforano i limiti di richieste dei tracker.',
  'integrations.rematchLabel': 'Cerca di nuovo dopo (giorni)',
  'integrations.rematchHelp': 'Predefinito: 7. Usa 0 per cercare ogni orfano a ogni scansione.',
  'integrations.autoApproveThresholdsDescription':
    'Un match pari o sopra la sua soglia viene segnato come consigliato nella coda di revisione. Niente viene mai eseguito senza la tua approvazione, a meno che tu non attivi l’esecuzione automatica qui sotto.',
  'integrations.executionTitle': 'Esecuzione',
  'integrations.executionDescription':
    'Cosa succede quando approvi un match: come vengono controllati i suoi dati e se i match consigliati partono da soli.',
  'integrations.skipRecheckLabel': 'Salta il recheck del client quando Nazgarr ha verificato al 100%',
  'integrations.skipRecheckHelp':
    'Disattivato di default. Quando il controllo completo ha appena verificato ogni pezzo, senza file extra mancanti e con lo stesso info hash, il torrent viene aggiunto al client come già completo, senza rileggere tutti i dati una seconda volta. In tutti gli altri casi il client fa il recheck come al solito. Tra il controllo e l’aggiunta c’è un breve intervallo in cui una modifica a un file passerebbe inosservata.',
  'integrations.skipRecheckNeedsVerify': 'Richiede che "Verifica ogni pezzo prima di eseguire" sia attivo.',
  'integrations.verifyLabel': 'Verifica ogni pezzo prima di eseguire',
  'integrations.verifyHelp':
    'Attivo di default. Quando approvi un match, tutti i pezzi del torrent vengono prima controllati sui tuoi file, esattamente come il recheck del client, e hardlink e torrent vengono aggiunti solo se lo supererà. Se il controllo fallisce non si tocca niente. Legge tutto il contenuto, quindi i file grandi richiedono qualche minuto. Disattivalo per eseguire subito e affidarti ai pezzi campione controllati durante il match.',
  'integrations.autoExecuteLabel': 'Esegui automaticamente i match consigliati',
  'integrations.autoExecuteHelp':
    'Disattivato di default. Se attivo, ogni scansione esegue da sola i match consigliati: crea gli hardlink e aggiunge i torrent al tuo client (sempre con un recheck completo) senza chiedere. Lascialo disattivato per approvarli uno per uno.',

  'integrations.addInstance': 'Aggiungi istanza',
  'integrations.addInstanceTitled': 'Aggiungi istanza {name}',
  'integrations.editInstanceTitled': 'Modifica istanza {name}',
  'integrations.noInstances': 'Nessuna istanza configurata.',
  'integrations.instanceLabel': 'Etichetta',
  'integrations.instanceUrl': 'URL',
  'integrations.urlSuggestion': 'es. {url}',
  'integrations.instanceApiKey': 'API key',
  'integrations.apiKeyHelp': 'La trovi in Settings → General di {name}.',
  'integrations.instanceEnabled': 'Attiva',
  'integrations.createInstanceFailed': 'Impossibile aggiungere l’istanza: {message}',

  'integrations.priority': 'Priorità',
  'integrations.priorityHelp': 'I valori più alti vengono interrogati per primi, quando un resolver li userà.',
  'integrations.timeoutSeconds': 'Timeout (secondi)',
  'integrations.basicAuth': 'HTTP basic auth',
  'integrations.basicAuthDescription': 'Per un’istanza dietro un reverse proxy con autenticazione basic.',
  'integrations.basicAuthUsername': 'Nome utente',
  'integrations.basicAuthPassword': 'Password',
  'integrations.testConnection': 'Prova connessione',
  'integrations.connectedSuccess': 'Connesso — v{version}.',
  'integrations.connectionFailed': 'Connessione non riuscita: {message}',
  'integrations.deleteInstanceTitle': 'Eliminare l’istanza {label}?',
  'integrations.deleteInstanceDescription': 'Nazgarr smette di leggere da questa istanza di {name}. L’istanza stessa non viene toccata.',
  'integrations.webhook.title':
    'Webhook',
  'integrations.webhook.dialogTitle':
    'Webhook di {label}',
  'integrations.webhook.description':
    'Quando {name} importa, aggiorna, rinomina o cancella un file, Nazgarr aggiorna subito solo quel file: niente scansione, si sveglia solo il suo disco, e il torrent da cui è stato importato risulta subito collegato.',
  'integrations.webhook.why':
    'La scansione completa resta, e prende anche quello che il webhook non vede (file copiati a mano, eventi persi durante un riavvio).',
  'integrations.webhook.enable':
    'Attiva il webhook',
  'integrations.webhook.url':
    'URL',
  'integrations.webhook.password':
    'Password',
  'integrations.webhook.copy':
    'Copia {what}',
  'integrations.webhook.shownOnce':
    'La password si vede solo adesso: se la perdi, rigenerala.',
  'integrations.webhook.step1':
    'In {name}: Settings › Connect › + › Webhook.',
  'integrations.webhook.step2':
    'Incolla l’URL, metodo POST; come nome utente scrivi quello che vuoi, come password quella qui sopra.',
  'integrations.webhook.step3Radarr':
    'Accendi On Import, On Upgrade, On Rename e On Movie File Delete.',
  'integrations.webhook.step3Sonarr':
    'Accendi On Import, On Upgrade, On Rename e On Episode File Delete.',
  'integrations.webhook.step4':
    'Premi Test e salva: qui comparirà l’evento ricevuto.',
  'integrations.webhook.reachability':
    'L’URL è quello con cui apri Nazgarr ora: se {name} gira in un altro container, usa l’indirizzo con cui lui raggiunge Nazgarr (es. http://nazgarr:3019).',
  'integrations.webhook.lastEvent':
    'Ultimo evento: {event}, {when} ({detail}).',
  'integrations.webhook.noEventYet':
    'Webhook attivo, nessun evento ricevuto da {name}: premi Test nella sua connessione.',
  'integrations.webhook.regenerate':
    'Rigenera la password',
  'integrations.webhook.regenerateTitle':
    'Rigenerare la password del webhook?',
  'integrations.webhook.regenerateDescription':
    'Quella di adesso smette subito di valere: dovrai incollare la nuova in {name}.',
  'integrations.webhook.disable':
    'Disattiva',
  'integrations.webhook.disableTitle':
    'Disattivare il webhook?',
  'integrations.webhook.disableDescription':
    'Gli eventi di {name} verranno rifiutati: togli anche la connessione da {name}.',
  'integrations.webhook.searchLabel':
    'Cerca sui tracker un file appena importato',
  'integrations.webhook.searchHelp':
    'Per tutte le istanze. Spento: un file nuovo si cerca alla prossima scansione, come sempre.',
} as const
