export const dashboard = {
  'dashboard.windowAll': 'Tutto',
  'dashboard.libraryHealth': 'Salute della libreria',
  'dashboard.healthGreat': 'Ottima',
  'dashboard.healthGood': 'Buona',
  'dashboard.healthFair': 'Discreta',
  'dashboard.healthPoor': 'Da sistemare',
  'dashboard.healthNoHistory': 'Nessuna scansione precedente in questo periodo da confrontare',
  'dashboard.ptsVsAgo': '{delta} punti rispetto a {days}d fa',
  'dashboard.healthHistory': 'Storico della salute',
  'dashboard.notEnoughHistory': 'Non c’è ancora abbastanza storico in questo periodo.',

  'dashboard.noPreviousScan': 'Nessuna scansione precedente da confrontare',
  'dashboard.trendImproving': 'In miglioramento',
  'dashboard.trendWorsening': 'In peggioramento',
  'dashboard.trendStable': 'Stabile',
  'dashboard.filesCount': '{count} file',
  'dashboard.torrentsCount': '{count} torrent',

  'dashboard.hardlinkedMedia': 'Media con hardlink',
  'dashboard.seedingOfTotal': '{seeding} di {total}',
  'dashboard.hardlinkedDescription': 'Quota della tua libreria (per dimensione) collegata con hardlink a un torrent che un client ha in seed.',
  'dashboard.viewOrphanedMedia': 'Vedi i media orfani',

  'dashboard.orphanedTorrents': 'Torrent orfani',
  'dashboard.orphanedSubline': '{count} file · {size} non nella libreria',
  'dashboard.orphanedDescription':
    'File nelle tue cartelle torrent che nessun client torrent sta seguendo. Quelli presenti anche nella libreria vengono cercati per rimetterli in seed.',
  'dashboard.viewOrphanedTorrents': 'Vedi i torrent orfani',

  'dashboard.notImported': 'Triage',
  'dashboard.notImportedDescription':
    'Torrent in seed senza hardlink nella tua libreria: vecchie release sostituite da un upgrade, copie o download mai importati.',
  'dashboard.viewNotImported': 'Smista i non importati',

  'dashboard.duplicates': 'Duplicati',
  'dashboard.duplicatesSubline': '{count} file che sprecano spazio · {hardlinks} doppi dello stesso file',
  'dashboard.duplicatesDescription':
    'Copie identiche dello stesso contenuto su inode diversi (lo spazio indicato), più percorsi che puntano due volte allo stesso file.',
  'dashboard.viewDuplicates': 'Vedi i duplicati',
  'dashboard.noLibrary': 'Nessuna cartella media impostata: Nazgarr lavora solo sui tuoi torrent e sui tuoi upload.',
} as const
