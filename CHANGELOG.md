# Changelog

Every stable release of Nazgarr, newest first. The app shows a short version of each entry after an update and, when a newer stable is available, before updating (`nazgarr/release_notes.json`). Test builds (`:nightly`, `:dev`) have no notes of their own: they get the next stable's notes when it is promoted.

Each section starts with `## X.Y.Z - YYYY-MM-DD` and has up to four parts: **Breaking changes** (what you need to do before or after updating), **New**, **Bug fixes** and **Chores** (technical work you will hardly notice). Promoting a version to stable copies its section into the GitHub Release.


## 0.9.0 - 2026-10-05

### Breaking changes

- **The default port is now 3019** (it was 8080), inside the container too. A container created with `"8080:8080"` no longer answers after the update: change the mapping to `"8080:3019"` to keep the old address, or `"3019:3019"`. On Unraid, set the WebUI Port's container port to 3019. The Python package (`nazgarr serve`, `install-service`) defaults to 3019 too.
- **Image hosts changed.** PTPImg (offline), Imgbox, Pixhost, OnlyImage, Dalexni, utp.pm and Seedpool CDN are gone, and there are no anonymous hosts any more. The available ones are PTScreens, Passtheima, imageride and ImgBB, each with its API key; the PTScreens and ImgBB keys move over by themselves. Enter the key of at least one host in Settings › Upload › Images, or uploads with screenshots stop with a clear error. Lensdump (paid API) is now an example plugin to install.
- **For plugin authors:** a plugin must import only `nazgarr.sdk` (now 1.2); Nazgarr's internal modules moved.

### New

- **Reseeding:** a queued reseed can get its own category and tags in the client, like an upload; a failed or stuck execution can be deleted so the next scan proposes it again.
- **Setup:** "Check paths" on each torrent client shows whether its files map to a disk and proposes the mapping; disks come from the folders mounted in the container; path and folder problems show up as warnings instead of failing silently. The tutorial follows the real setup, and a new tour, "The rest of Nazgarr", presents uploads (on an example that creates nothing), notifications, instances, API keys, plugins and updates.
- **Uploads:** remux and source are read from MediaInfo when the name says nothing (Dolby Vision profile 7, VC-1, lossless audio with PGS, remux bitrate, MakeMKV's "Original source medium"), and the type tag explains why. An AI upscale is an edition, and `{edition}` is in the default naming templates. A warning above the release name and in the confirmation when no source was found.
- **Exclusions:** the defaults follow Plex's and Jellyfin's naming (every image, nfo, theme music); new presets for extras (off by default), macOS and Windows system files and `.torrent` files.
- **Notifications:** services are instances, next to the webhooks, each with its type, settings, test and last delivery.
- **Updates:** an optional automatic check every 12 hours (off by default); the notes of a new version before updating, and what is new after.
- **Plugins:** each one can be switched on and off from Settings › Plugins without a restart; image hosts are plugins too.

### Bug fixes

- Reseeds and uploads stayed stopped in qBittorrent set to "do not start the download automatically" or to stop after checking files.
- With qBittorrent's "create subfolder" content layout, a single-file reseed downloaded again instead of seeding the hardlink.
- When adding a torrent failed but the client got it anyway (a slow tracker), the hardlinks were removed and the client downloaded the file; "Retry" could not recover it.
- A renamed remux (e.g. `film.mkv`) came out as an encode with no source; a joined "BDRemux" was not a remux, so Dolby Vision profile 8 never made it HYBRID.
- An edition (e.g. an AI upscale) could disappear from the release name; a film with "Sample" in its title came out empty.
- Posters and covers not named exactly as expected, and macOS `._` files, showed up as library files.
- The watched folder could leave files behind when they kept their original names.
- Two runs could start at the same time; removal warnings ignored some clients.
- The dupe check read traits from the wrong name; auto-match numbered episodes in the default order instead of the chosen one.
- The interface is optimized for phones and tablets: a sidebar that slides in, bigger touch targets, tables and dialogs that fit the screen, info popovers that open with a tap, and a confirmation before every delete.

### Chores

- Database migrations are numbered steps; settings are declared once, typed.
- The Python package is split by domain.
- Faster views and scans (cached dashboard and library, pages loaded on demand, hashes only for changed files, shared tracker rate limit), clients closed after use.
- Tests, documentation and CI updates.
