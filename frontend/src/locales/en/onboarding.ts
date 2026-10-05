// Il tour del primo accesso (src/onboarding). Tono neutro, con al massimo una
// strizzata d'occhio fantasy per passo: mai nomi né citazioni letterali.
export const onboarding = {
  'onboarding.welcome.title': 'Welcome to Nazgarr',
  'onboarding.welcome.description':
    'One place to find your media, your seeding folders and your torrent clients, and to bind them together with hardlinks. A few minutes of setup and the rest is guided.',
  'onboarding.welcome.approval':
    'Nothing passes without your word: Nazgarr never creates a hardlink, adds a torrent or uploads anything until you approve it in a review queue. Automatic execution exists, but it is off and stays off unless you turn it on.',
  'onboarding.welcome.needTitle': 'Good to have at hand',
  'onboarding.welcome.needPaths':
    "Which folders you mounted in this container (e.g. /data, with media/ and torrents/ inside, or /mnt/disk1 and /mnt/disk2).",
  'onboarding.welcome.needClient': "Your torrent client's address and login (qBittorrent, qui, Deluge, Transmission or rTorrent/ruTorrent).",
  'onboarding.welcome.needTmdb':
    "A free TMDB API key (or Radarr/Sonarr), to recognize movies and shows.",
  'onboarding.welcome.needTracker': 'For each private tracker: its address and your API token.',
  'onboarding.welcome.ask.upload': 'Will you upload new torrents?',
  'onboarding.welcome.ask.uploadHelp': 'Adds the image hosts and the upload settings to the path.',
  'onboarding.welcome.ask.arr': 'Do you use Radarr or Sonarr?',
  'onboarding.welcome.ask.arrHelp': 'Optional: their import history explains why a torrent is not in your library.',
  'onboarding.welcome.later': 'Later',
  'onboarding.welcome.start': 'Start the setup',

  'onboarding.checklist.title': 'Getting started',
  'onboarding.checklist.description': 'Each step completes on its own as soon as the configuration is there, wherever you set it.',
  'onboarding.checklist.readyTitle': 'Everything is in place',
  'onboarding.checklist.readyDescription': 'The road goes ever on: the optional steps are still here whenever you want them.',
  'onboarding.checklist.hide': 'Hide',
  'onboarding.checklist.finish': 'Done',
  'onboarding.checklist.optional': 'optional',
  'onboarding.checklist.guide': 'Guide me',

  'onboarding.step.storage.title':
    "Storage",
  'onboarding.step.storage.summary':
    "Your disks: the torrent folder on each and, if you have one, the media library.",
  'onboarding.step.clients.title':
    "Clients",
  'onboarding.step.clients.summary':
    "Connect your torrent client and check that Nazgarr finds its files.",
  'onboarding.step.metadata.title':
    "Integrations",
  'onboarding.step.metadata.summary':
    "A TMDB API key (or Radarr/Sonarr), to recognize movies and shows.",
  'onboarding.step.arr.title': 'Radarr / Sonarr',
  'onboarding.step.arr.summary': 'Their import history: why a torrent never reached the library.',
  'onboarding.step.trackers.title': 'Trackers',
  'onboarding.step.trackers.summary': 'Your private trackers, to find what you can seed again.',
  'onboarding.step.exclusions.title': 'Exclusions',
  'onboarding.step.exclusions.summary': 'Samples, extras and folders to leave out of every count.',
  'onboarding.step.reseeding.title':
    "Matching & approval",
  'onboarding.step.reseeding.summary':
    "How often to scan on its own, and how sure a match must be before it is recommended.",
  'onboarding.step.upload.title':
    "Images & releases",
  'onboarding.step.upload.summary': 'Image hosts for the screenshots, and the upload defaults.',
  'onboarding.step.first_scan.title': 'First scan',
  'onboarding.step.views.title': 'Tour of the views',
  'onboarding.step.first_scan.summary': 'Scan everything once. A long one is the right time for a second breakfast.',

  'onboarding.restart.title': 'Getting started tour',
  'onboarding.restart.description': 'The guided setup of the first access, with its checklist on the dashboard.',
  'onboarding.restart.button': 'Restart the tour',
  'onboarding.tour.next': 'Next',
  'onboarding.tour.back': 'Back',
  'onboarding.tour.done': 'Done',
  'onboarding.tour.continue': 'Continue: {next}',
  'onboarding.tour.waiting': 'Go ahead, the tour moves on by itself.',

  'onboarding.tour.storage.intro.title': 'Your disks',
  'onboarding.tour.storage.intro.body':
    "A disk is a filesystem as this container sees it: one of the folders you mounted. Hardlinks only work inside one filesystem, so a disk keeps its torrent folders and its media folders (if any) on the same one.\nWith a single shared mount (e.g. /data with media/ and torrents/ inside) one disk is enough; with disks mounted one by one (/mnt/disk1, /mnt/disk2) you add one for each.",
  'onboarding.tour.storage.add.title': 'Add a disk',
  'onboarding.tour.storage.add.body': 'Click "Add disk" to register the first one.',
  'onboarding.tour.storage.label.title': 'A name',
  'onboarding.tour.storage.label.body': 'Anything that tells you which disk this is: "main", "disk1", "nvme".',
  'onboarding.tour.storage.root.title': 'Where it is mounted',
  'onboarding.tour.storage.root.body':
    "The path inside this container, not on your host: one of the mounted folders, already proposed. Below the disks you find the folders you mounted, with a warning if two are the same filesystem mounted separately (hardlinks across mounts do not work) or if the Unraid share and the single disks are mounted together.",
  'onboarding.tour.storage.create.title': 'Create it',
  'onboarding.tour.storage.create.body': 'Nazgarr checks that the path exists and remembers which filesystem it is on.',
  'onboarding.tour.storage.media.title':
    'The media folders',
  'onboarding.tour.storage.media.body':
    "Now your library, the one Plex, Jellyfin or Radarr/Sonarr use: \"Add\" for each folder (e.g. movies/ and tv/, even separate). Every file inside is matched against what you seed. Optional: without them Nazgarr works on your torrents and uploads, but reseeding finds nothing, because it recognizes content from library files. A folder on another filesystem must be added as a disk of its own.",
  'onboarding.tour.storage.seeding.title':
    'The torrent folders',
  'onboarding.tour.storage.seeding.body':
    'Click "Add" and pick the folder where your torrent client downloads and seeds (e.g. torrents/). If you use more than one (e.g. one for cross-seed), add them all. Seeding files without a hardlink in the library end up in Triage; library files without a torrent are "orphaned".',
  'onboarding.tour.storage.new.title': 'New hardlinks (optional)',
  'onboarding.tour.storage.new.body':
    'Where a reseed creates its hardlinks, and where the client is told to seed them. Empty means the first torrent folder, which is fine in most cases.',
  'onboarding.tour.storage.upload.title': 'Uploads (optional)',
  'onboarding.tour.storage.upload.body':
    'The same for your uploads: where their files are linked and seeded. Empty means the first torrent folder.',
  'onboarding.tour.storage.verify.title':
    'Test the disk',
  'onboarding.tour.storage.verify.body':
    'Checks that the folders exist and that a hardlink really goes from the torrent folder to every other one, with an empty test file removed right away. Keep watch like a tower: run it again whenever you remount or move a disk.',

  'onboarding.tour.clients.add.title': 'Add your torrent client',
  'onboarding.tour.clients.add.body': 'Click "Add client". Nazgarr only reads from it, until you approve a reseed or an upload.',
  'onboarding.tour.clients.type.title': 'Which client',
  'onboarding.tour.clients.type.body': 'qBittorrent (or qui if you manage several qBittorrent instances with it), Deluge, Transmission or rTorrent/ruTorrent. Plugins can add more.',
  'onboarding.tour.clients.url.title': 'Its address',
  'onboarding.tour.clients.url.body':
    'As this container reaches it: with Docker on the same network it is usually the container name (http://qbittorrent:8080), not localhost.',
  'onboarding.tour.clients.credentials.title': 'Login',
  'onboarding.tour.clients.credentials.body': 'The WebUI username and password (for Deluge, only its password; for qui, its API key and the instance number). Stored encrypted.',
  'onboarding.tour.clients.create.title': 'Create it',
  'onboarding.tour.clients.create.body': 'Then we test the connection.',
  'onboarding.tour.clients.test.title': 'Test the connection',
  'onboarding.tour.clients.test.body': 'Click "Test connection": it says how many torrents the client has. If it fails, check the address and the WebUI login.',
  'onboarding.tour.clients.paths.title': 'Check the paths',
  'onboarding.tour.clients.paths.body':
    'The delicate part: the client and Nazgarr must find the same files, even if they see them from different folders. Click "Check paths": for every torrent Nazgarr looks for its file on the disks. If something is off it shows where it looked and suggests the right mapping, applied with one click. Run it again whenever you change the client mounts.',
  'onboarding.tour.clients.disks.title': 'Disks and paths (optional)',
  'onboarding.tour.clients.disks.body':
    "This is where you say how the client sees the disks. Three typical cases:\n• client and Nazgarr both mount /data: nothing to do;\n• the client mounts only the torrent folder as /downloads: disk folder torrents = /downloads;\n• Unraid with /mnt/disk1 and /mnt/disk2 in Nazgarr and the share /mnt/user/data in the client: on each disk, folder data = /mnt/user/data.\nWhen in doubt, \"Check paths\" suggests it for you. Once you turn on one disk, the others count only if turned on too.",
  'onboarding.tour.clients.labels.title': 'Category and tags for uploads',
  'onboarding.tour.clients.labels.body': 'The category and the tags your uploads get on this client (e.g. tag "release"). Each upload can still change them.',

  'onboarding.tour.metadata.tmdb.title': 'TMDB',
  'onboarding.tour.metadata.tmdb.body':
    'The key that lets Nazgarr recognise what every file is. It is free: create an account on themoviedb.org, then Settings › API, and paste the API key (v3) here. Keep it hidden and safe: it is stored encrypted.',
  'onboarding.tour.metadata.tvdb.title': 'TVDB (optional)',
  'onboarding.tour.metadata.tvdb.body':
    "Only a last resort for episode orders, when Sonarr does not have the show or the files follow another order. You can leave it empty.",
  'onboarding.tour.metadata.radarr.title': 'Radarr',
  'onboarding.tour.metadata.radarr.body':
    'Its address and API key (Radarr › Settings › General). Its import history tells why a torrent never reached the library, and recognises files faster than by name.',
  'onboarding.tour.metadata.sonarr.title': 'Sonarr',
  'onboarding.tour.metadata.sonarr.body': 'The same for series: address and API key from Sonarr › Settings › General.',

  'onboarding.tour.trackers.add.title': 'Add a tracker',
  'onboarding.tour.trackers.add.body': 'Click "Add tracker" for each private tracker you use.',
  'onboarding.tour.trackers.preset.title': 'A known tracker?',
  'onboarding.tour.trackers.preset.body': 'Pick it from the list: name, address and upload settings are filled in. Not in the list? Fill in the fields by hand.',
  'onboarding.tour.trackers.url.title': 'Its address',
  'onboarding.tour.trackers.url.body': 'The site address, e.g. https://mytracker.example. The API is called there.',
  'onboarding.tour.trackers.token.title': 'Your API token',
  'onboarding.tour.trackers.token.body':
    'On UNIT3D trackers: your profile › Settings › API key. It lets Nazgarr search the catalogue, nothing more. Keep it hidden and safe: it is stored encrypted.',
  'onboarding.tour.trackers.announce.title': 'Announce URL (uploads only)',
  'onboarding.tour.trackers.announce.body':
    'Only needed to create torrents for your own uploads: it contains your passkey (from the upload page of the tracker). Leave it empty if you only reseed.',
  'onboarding.tour.trackers.create.title': 'Create it',
  'onboarding.tour.trackers.create.body': 'You can add more trackers later the same way.',
  'onboarding.tour.trackers.client.title': 'Which client seeds it',
  'onboarding.tour.trackers.client.body': 'Where the reseeds of this tracker are added, e.g. a client just for private trackers. Default: the first enabled one.',
  'onboarding.tour.trackers.language.title': 'Its language',
  'onboarding.tour.trackers.language.body': 'For upload names: the title in this language, its audio first, and how subtitles are written.',
  'onboarding.tour.trackers.seed.title': 'Minimum seeding',
  'onboarding.tour.trackers.seed.body':
    'The hit and run rule of the tracker (seed time and/or ratio). Triage then tells which old torrents you can remove safely. Optional.',
  'onboarding.tour.trackers.profile.title': 'Upload profile',
  'onboarding.tour.trackers.profile.body': 'How uploads to this tracker are named and categorised. A known tracker already has one: change it only if needed.',
  'onboarding.tour.exclusions.presets.title': 'Ready-made exclusions',
  'onboarding.tour.exclusions.presets.body':
    'Sets of files that never count: media server metadata (artwork, .nfo) is on by default; samples and scene leftovers can be added. Excluded files stay on disk, they are just left out of states, counts and searches.',
  'onboarding.tour.exclusions.custom.title': 'Your own patterns',
  'onboarding.tour.exclusions.custom.body': 'Anything else to leave out, as patterns on the path (e.g. */Extras/*). You can also exclude a file or a folder by right-clicking it in the Library.',

  'onboarding.tour.reseeding.schedule.title': 'Automatic scans',
  'onboarding.tour.reseeding.schedule.body':
    "Automatic scans are off until you choose when: every 6 hours suits most libraries. Without one, Nazgarr scans only when you click \"Scan now\". Even so nothing is linked or added without you: suggestions wait in the queue.",
  'onboarding.tour.reseeding.search.title': 'What gets searched',
  'onboarding.tour.reseeding.search.body':
    'Every scan looks for the library files that do not seed. With cross-seeds on, a file seeding on one tracker is also searched on the others.',
  'onboarding.tour.reseeding.thresholds.title': 'How sure is sure',
  'onboarding.tour.reseeding.thresholds.body':
    'Above these confidences a match is marked as recommended; below, it waits in the queue as a proposal. Either way, nothing runs until you approve it, unless you turn on automatic execution below.',
  'onboarding.tour.reseeding.execution.title': 'Before anything is done',
  'onboarding.tour.reseeding.execution.body':
    'The full check reads every piece before a hardlink or a torrent is created, so the client recheck cannot fail. Automatic execution is off, and stays off unless you choose otherwise.',

  'onboarding.tour.upload.hosts.title': 'Image hosts',
  'onboarding.tour.upload.hosts.body':
    'Where the screenshots of your uploads go, in this order: drag to change it, remove the ones you do not want. Imgbox and Pixhost need no key; for the others paste your API key on the right.',
  'onboarding.tour.upload.screenshots.title': 'Screenshots',
  'onboarding.tour.upload.screenshots.body': 'How many per upload, and whether HDR frames are tone-mapped so they do not look washed out.',
  'onboarding.tour.upload.description.title': 'Description',
  'onboarding.tour.upload.description.body': 'A header and a signature in BBCode around the description Nazgarr writes for each upload.',
  'onboarding.tour.upload.names.title': 'File names',
  'onboarding.tour.upload.names.body':
    'How the files inside a new torrent are named: the names of the hardlinked release if there is one, otherwise this pattern, for library files and watched-folder releases. Turn off the automatic rename to keep the original names; each upload can still choose.',

  'onboarding.tour.first_scan.run.title': 'The first scan',
  'onboarding.tour.first_scan.run.body':
    'Click "Scan now": Nazgarr reads your disks, recognises every file, indexes your clients and searches your trackers. It only reads: nothing is linked, added or moved.',
  'onboarding.tour.first_scan.progress.title': 'It takes a while',
  'onboarding.tour.first_scan.progress.body':
    'The progress is at the bottom right, and you can keep using Nazgarr meanwhile. A first scan of a large library is the right time for a second breakfast. Meanwhile, a look around.',

  'onboarding.tour.views.intro.title': 'A look from the tower',
  'onboarding.tour.views.intro.body': 'Like a tower that keeps watch, the Dashboard sees everything at once. A short tour of where things are; the numbers fill in as the scan goes.',
  'onboarding.tour.views.health.title': 'Library health',
  'onboarding.tour.views.health.body': 'How much of your library, by size, is seeding through a hardlink. Next to it, how it changed over time.',
  'onboarding.tour.views.metrics.title': 'What needs a look',
  'onboarding.tour.views.metrics.body':
    'Hardlinked media, orphaned torrents, torrents to triage and duplicates, with the trend since the last scan. Each card opens the matching list.',
  'onboarding.tour.views.changes.title': 'What changed',
  'onboarding.tour.views.changes.body': 'File by file, what changed since the previous scan, and the history of the scans.',
  'onboarding.tour.views.filter.title': 'One tracker at a time',
  'onboarding.tour.views.filter.body': 'Every view can count all torrents, only your configured trackers, or a single one. The choice is remembered.',
  'onboarding.tour.views.library.title': 'Your library',
  'onboarding.tour.views.library.body':
    'The files of your media folders, as a folder tree or as posters: switch here. Right-click a file or a folder to upload it, reseed it or exclude it.',
  'onboarding.tour.views.states.title': 'Seeding or orphaned',
  'onboarding.tour.views.states.body':
    'Seeding: a hardlink seeds in a client. Orphaned: nothing seeds it, so it is a candidate for a reseed. Click a card to filter.',
  'onboarding.tour.views.not_imported.title': 'Triage',
  'onboarding.tour.views.not_imported.body':
    'Not every file that wanders is lost: these seed without a hardlink in your library, each with its reason (replaced by an upgrade, a copy, never imported). With a seeding requirement on the tracker, a green OK says which can go; anything else to check before removing one (files shared with another torrent, a client error) sits in the popover next to it.',
  'onboarding.tour.views.review.title': 'The review queue',
  'onboarding.tour.views.review.body':
    'Every proposal waits here, with its confidence and what it would do. Approve or reject: nothing passes without your word. The road goes ever on: the next scans keep it filled.',
  'onboarding.tour.storage.watch.title': 'A folder for your releases (optional)',
  'onboarding.tour.storage.watch.body':
    'If you release your own encodes: what you put in this folder starts an upload on its own, up to the decision, where it waits for your approval. Once it seeds, it moves to the uploads folder.',
  'onboarding.tour.upload.releases.title': 'Your releases',
  'onboarding.tour.upload.releases.body':
    'Your releaser name, used as the group of the uploads from the watched folder and of every upload whose name has no group, and how sure a TMDB match must be to be confirmed on its own, for every upload.',
  'onboarding.tour.views.pack.title':
    'Compose a pack',
  'onboarding.tour.views.pack.body':
    'Episodes downloaded one at a time, even ones already seeding with their own torrent, become a season pack or a complete pack: pick them (Shift-click for a run) and create the pack. The upload starts from a new folder of hardlinks, one subfolder per season, subtitles included. Episodes from different releases need your confirmation.',
  'onboarding.tour.views.torrents.title':
    'Your torrents',
  'onboarding.tour.views.torrents.body':
    'Files: what your seeding folders hold, as a tree, with the same filters and the same pack picking (no media folder needed). Triage: the torrents that never made it to the library.',
  'onboarding.tour.views.uploads.title':
    'Your uploads',
  'onboarding.tour.views.uploads.body':
    'In progress and history, one row per upload with the outcome on each tracker. The trash removes the record only (trackers, clients and disk stay as they are); on an upload that is running it cancels it.',
  'onboarding.tour.upload.single_file.title':
    'A single file, not a folder',
  'onboarding.tour.upload.single_file.body':
    'When the only file going into the torrent sits in a folder, the torrent can be just that file. Choose whether the file seeds inside its folder or directly in the releases folder. Off by default.',
} as const
