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
} as const
