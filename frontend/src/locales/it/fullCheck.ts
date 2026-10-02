export const fullCheck = {
  'fullCheck.button': 'Controllo completo degli hash',
  'fullCheck.hint': 'Verifica ogni pezzo del torrent sui file locali, come il recheck del client',
  'fullCheck.title': 'Controllo completo degli hash',
  'fullCheck.explanation':
    'Scarica il .torrent e verifica il 100% dei suoi pezzi sui file locali, esattamente come il recheck del client, compresi i pezzi condivisi tra due file. I file vengono letti dove li vede il client (gli hardlink creati dall’esecuzione) o, in mancanza, dalla libreria. Sola lettura: non cambia niente. Legge tutto il contenuto, quindi un file grande può richiedere qualche minuto; continua anche se chiudi questa finestra.',
  'fullCheck.start': 'Avvia il controllo',
  'fullCheck.runAgain': 'Ripeti',
  'fullCheck.queued': 'In attesa che finisca un altro controllo…',
  'fullCheck.downloadingTorrent': 'Download del .torrent…',
  'fullCheck.cancelled': 'Controllo annullato.',
  'fullCheck.piecesSummary': '{ok} di {total} pezzi verificati · {size} per pezzo',
  'fullCheck.verdictOk':
    'I dati locali sono identici al torrent. Se il client non lo mette ancora in seed, sta cercando altrove: controlla il percorso di salvataggio e il nome della cartella indicati al client.',
  'fullCheck.verdictOkNotInSeed':
    'I dati della libreria sono identici al torrent, ma alcuni file non sono dove li cerca il client (letti dalla libreria, non dalla cartella di seed): gli hardlink mancano o hanno un nome diverso.',
  'fullCheck.verdictMismatch':
    '{count} pezzi sono diversi dal torrent: il file locale non è lo stesso del torrent (release, edit o re-encode diversi), quindi non può andare in seed con questo torrent.',
  'fullCheck.verdictUnreadable':
    '{count} pezzi non si possono verificare perché un file manca o è più corto del previsto. Il client dovrebbe scaricarli.',
  'fullCheck.verdictHashChanged':
    'Tutti i pezzi corrispondono, ma il .torrent scaricato ora ha un info hash diverso da quello aggiunto al client: il tracker ha sostituito il torrent.',
  'fullCheck.readFromSeed': 'cartella di seed',
  'fullCheck.readFromLibrary': 'libreria',
  'fullCheck.noLocalFile': 'Nessun file locale trovato',
  'fullCheck.sizeDiffers': 'Dimensione locale {local}, il torrent si aspetta {expected}',
  'fullCheck.fileMismatch': '{count} pezzi diversi, il primo a {offset} nel file',
  'fullCheck.fileUnreadable': '{count} pezzi non verificabili (file mancante o più corto)',
  'fullCheck.expectedHash': 'Aggiunto al client come {hash}',
} as const
