export const uploadSettings = {
  'uploadSettings.screenshotsTitle': 'Screenshot',
  'uploadSettings.screenshotsDescription': 'Vale per il prossimo upload preparato, non in modo retroattivo su quelli già pronti.',
  'uploadSettings.screenshotCountLabel': 'Numero di screenshot',
  'uploadSettings.screenshotCountDescription': 'Fotogrammi equidistanti, esclude il primo/ultimo 5% della durata.',
  'uploadSettings.tonemapLabel': 'Tonemap HDR negli screenshot',
  'uploadSettings.tonemapDescription':
    'Converte HDR→SDR (algoritmo mobius) prima di catturare gli screenshot — senza, una sorgente HDR sembra slavata/scura una volta interpretata come SDR.',
  'uploadSettings.descriptionTitle': 'Descrizione',
  'uploadSettings.descriptionHeaderLabel': 'Intestazione della descrizione',
  'uploadSettings.descriptionHeaderHelp':
    'Testo (es. BBCode) messo prima della descrizione generata dal template del tracker — lascia vuoto per non aggiungere niente.',
  'uploadSettings.descriptionHeaderSaved': 'Intestazione salvata.',
  'uploadSettings.saveHeaderButton': 'Salva intestazione',
  'uploadSettings.signatureLabel': 'Firma',
  'uploadSettings.signatureHelp':
    'Testo (es. BBCode) aggiunto alla fine di ogni descrizione — lascia vuoto per non aggiungere niente. Dopo segue sempre una breve riga "Uploaded with Nazgarr" con la versione.',
  'uploadSettings.signatureSaved': 'Firma salvata.',
  'uploadSettings.saveSignatureButton': 'Salva firma',
  'uploadSettings.apiKeysLabel': 'API key',
  'uploadSettings.apiKeysHelp': 'Solo gli host che la chiedono; gli altri caricano in modo anonimo.',
  'uploadSettings.imageHostsTitle': 'Host di immagini',
  'uploadSettings.imageHostsDescription':
    'Priorità e stato a sinistra, API key a destra — si prova il primo host attivo, se fallisce si usa il successivo. Imgbox e Pixhost non ne richiedono una.',
  'uploadSettings.noApiKeyRequired': 'nessuna api_key richiesta',
  'uploadSettings.priorityOrderLabel': 'Ordine di priorità degli host di immagini',
  'uploadSettings.priorityOrderHelp': 'Trascina per riordinare — si prova il primo, se fallisce si usa il successivo.',
  'uploadSettings.priorityOrderSaved': 'Ordine di priorità salvato.',
  'uploadSettings.dragToReorder': 'Trascina per riordinare {label}',
  'uploadSettings.disable': 'Disattiva',
  'uploadSettings.hostDisabled': '{host} disattivato.',
  'uploadSettings.hostEnabled': '{host} attivato.',
  'uploadSettings.fileNamesTitle': 'Nomi dei file nel torrent',
  'uploadSettings.fileNamesDescription':
    'Quando su un client non c’è un torrent con gli stessi file (hardlink), i file di un nuovo upload prendono un nome costruito da questo pattern, separato da punti come una release: niente ":" né accenti. Ogni upload può comunque tenere i nomi originali.',
  'uploadSettings.fileNamesReset': 'Torna al predefinito',
  'uploadSettings.releasesTitle': 'Le tue release',
  'uploadSettings.releasesDescription':
    'Per quello che rilasci tu: mettilo nella cartella osservata di un disco (Impostazioni › Archiviazione) e l’upload parte da solo, fino alla decisione. Quando è in seed, viene spostato nella cartella delle release: la cartella osservata è solo un ingresso.',
  'uploadSettings.releaserLabel': 'Nome del releaser',
  'uploadSettings.releaserDescription': 'Il gruppo in fondo ai nomi degli upload dalla cartella osservata (es. -NZG). Modificabile su ogni upload.',
  'uploadSettings.autoMatchLabel': 'Match TMDB automatico',
  'uploadSettings.autoMatchDescription':
    'Per ogni upload, a mano o dalla cartella osservata: un match almeno così sicuro (0-1) viene confermato da solo; sotto, o quando due titoli si somigliano, aspetta te. Cambia match lo riporta indietro. 0 lo disattiva. Predefinito: 0.9.',
} as const
