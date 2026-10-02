export const dashboard = {
  'dashboard.windowAll': 'All',
  'dashboard.libraryHealth': 'Library health',
  'dashboard.healthGreat': 'Great',
  'dashboard.healthGood': 'Good',
  'dashboard.healthFair': 'Fair',
  'dashboard.healthPoor': 'Needs attention',
  'dashboard.healthNoHistory': 'No earlier scan in this period to compare',
  'dashboard.ptsVsAgo': '{delta} pts vs {days}d ago',
  'dashboard.healthHistory': 'Health history',
  'dashboard.notEnoughHistory': 'Not enough history in this period yet.',

  'dashboard.noPreviousScan': 'No previous scan to compare',
  'dashboard.trendImproving': 'Improving',
  'dashboard.trendWorsening': 'Worsening',
  'dashboard.trendStable': 'Stable',
  'dashboard.filesCount': '{count} files',
  'dashboard.torrentsCount': '{count} torrents',

  'dashboard.hardlinkedMedia': 'Hardlinked media',
  'dashboard.seedingOfTotal': '{seeding} of {total}',
  'dashboard.hardlinkedDescription': 'Share of your media library (by size) hardlinked to a torrent that a client is seeding.',
  'dashboard.viewOrphanedMedia': 'View orphaned media',

  'dashboard.orphanedTorrents': 'Orphaned torrents',
  'dashboard.orphanedSubline': '{count} files · {size} not in the library',
  'dashboard.orphanedDescription':
    'Files in your torrent folders that no torrent client is tracking. Those also in the library are searched to seed them again.',
  'dashboard.viewOrphanedTorrents': 'View orphaned torrents',

  'dashboard.notImported': 'Triage',
  'dashboard.notImportedDescription':
    'Seeding torrents with no hardlink in your library: old releases replaced by an upgrade, copies, or downloads never imported.',
  'dashboard.viewNotImported': 'Triage not imported',

  'dashboard.duplicates': 'Duplicates',
  'dashboard.duplicatesSubline': '{count} files wasting space · {hardlinks} same-file doubles',
  'dashboard.duplicatesDescription':
    'Identical copies of the same content on different inodes (the space shown), plus paths that point to the same file twice.',
  'dashboard.viewDuplicates': 'View duplicates',
  'dashboard.noLibrary': 'No media folder set: Nazgarr is working on your torrents and uploads only.',
} as const
