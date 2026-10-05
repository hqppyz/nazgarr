export const exclusions = {
  'exclusions.tab': 'Esclusioni',
  'exclusions.presetsTitle': 'Preset',
  'exclusions.presetsDescription':
    'Pattern pronti per i file spazzatura più comuni. I file esclusi restano sul disco e vengono comunque scansionati. Sono solo nascosti di default in File media e File torrent e non vengono mai contati nei totali.',
  'exclusions.preset.media_server_metadata': 'Artwork e metadati dei media server (Plex, Jellyfin, Kodi)',
  'exclusions.preset.extras': 'Extra (trailer, featurette, scene eliminate, interviste…)',
  'exclusions.preset.system_files': 'File di sistema di macOS e Windows',
  'exclusions.preset.torrent_files': 'File .torrent',
  'exclusions.presetHelp.media_server_metadata':
    'Poster, fanart, loghi e miniature come li nominano Plex e Jellyfin, compresi quelli col nome del video: tutte le immagini, più nfo e musica del tema.',
  'exclusions.presetHelp.extras':
    'Le cartelle e i suffissi degli extra di Plex e Jellyfin. Sono video veri: esclusi spariscono dalle viste e dalle ricerche, ma un torrent che li contiene li ricrea comunque.',
  'exclusions.presetHelp.system_files':
    'I file "._" e .DS_Store che macOS lascia sui dischi condivisi, le cartelle nascoste dei volumi, Thumbs.db e desktop.ini.',
  'exclusions.preset.scene_junk': 'Spazzatura di scene/tracker',
  'exclusions.preset.qbittorrent_incomplete': 'File incompleti di qBittorrent',
  'exclusions.preset.utorrent_incomplete': 'File incompleti di uTorrent',
  'exclusions.preset.bitcomet_incomplete': 'File incompleti di BitComet',
  'exclusions.customTitle': 'Pattern personalizzati',
  'exclusions.customDescription':
    'Un pattern per riga, senza distinzione tra maiuscole e minuscole. Un pattern senza "/" corrisponde al nome del file a qualsiasi profondità (*.nfo). Un pattern con "/" corrisponde a quel percorso da qualsiasi cartella (sample/*).',
  'exclusions.stillUsedNote':
    'I file esclusi non attivano mai ricerche su TMDB o sui tracker, ma un file che fa parte di un torrent viene comunque usato quando quel torrent viene ricreato.',
  'exclusions.save': 'Salva i pattern',
  'exclusions.saved': 'Pattern di esclusione salvati.',
  'exclusions.presetsSaved': 'Preset di esclusione aggiornati.',
} as const
