export const exclusions = {
  'exclusions.tab': 'Exclusions',
  'exclusions.presetsTitle': 'Presets',
  'exclusions.presetsDescription':
    'Ready-made patterns for common junk. Excluded files stay on disk and are still scanned. They are just hidden by default in Media files and Torrent files and never counted in the totals.',
  'exclusions.preset.media_server_metadata': 'Media server artwork and metadata (Plex, Jellyfin, Kodi)',
  'exclusions.preset.extras': 'Extras (trailers, featurettes, deleted scenes, interviews…)',
  'exclusions.preset.system_files': 'macOS and Windows system files',
  'exclusions.preset.torrent_files': '.torrent files',
  'exclusions.presetHelp.media_server_metadata':
    'Posters, fanart, logos and thumbnails as Plex and Jellyfin name them, including those named like the video: every image, plus nfo files and theme music.',
  'exclusions.presetHelp.extras':
    'The extras folders and suffixes of Plex and Jellyfin. They are real videos: excluded, they leave the views and the searches, but a torrent that contains them still recreates them.',
  'exclusions.presetHelp.system_files':
    'The "._" and .DS_Store files macOS leaves on shared disks, the hidden folders of volumes, Thumbs.db and desktop.ini.',
  'exclusions.preset.scene_junk': 'Scene/tracker junk',
  'exclusions.preset.qbittorrent_incomplete': 'qBittorrent incomplete files',
  'exclusions.preset.utorrent_incomplete': 'uTorrent incomplete files',
  'exclusions.preset.bitcomet_incomplete': 'BitComet incomplete files',
  'exclusions.customTitle': 'Custom patterns',
  'exclusions.customDescription':
    'One pattern per line, case-insensitive. A pattern without "/" matches the file name at any depth (*.nfo). A pattern with "/" matches that path from any folder (sample/*).',
  'exclusions.stillUsedNote':
    'Excluded files never trigger TMDB or tracker lookups, but a file that is part of a torrent is still used when that torrent is recreated.',
  'exclusions.save': 'Save patterns',
  'exclusions.saved': 'Exclusion patterns saved.',
  'exclusions.presetsSaved': 'Exclusion presets updated.',
} as const
