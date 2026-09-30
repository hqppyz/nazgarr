# Nazgarr SDK: plugins, webhooks and API keys

Nazgarr can be extended in three ways:

- **Plugins**: Python packages that add adapters, such as a tracker, a torrent client, a media resolver, an image host or a notification service.
- **Webhooks**: signed HTTP calls for the events you choose.
- **API keys**: scripts and other services can use the same JSON API as the web UI.

SDK version: **1.0.0** (`nazgarr_sdk.SDK_VERSION`, [semantic versioning](https://semver.org): a breaking change bumps the major version).

## Rules that apply to everything here

- **Nothing changes files or torrent clients without your approval.** A plugin, an API key or a webhook receiver can only *propose* a change (a review, an upload job); the change runs after you approve it, as it does from the UI.
- **Plugins run inside Nazgarr with its permissions.** They can read the database and your files. Install only plugins you trust.
- **Secrets never come back.** Configuration fields marked as secret are stored encrypted and the API only says whether they are set. The same goes for API keys and webhook secrets, which are shown once.

---

## Installing plugins

List the pip packages in the `NAZGARR_PLUGINS` environment variable, separated by spaces or commas:

```yaml
environment:
  - NAZGARR_PLUGINS=nazgarr-deluge nazgarr-ntfy==0.3.1 git+https://github.com/you/nazgarr-thing
```

Or write them one per line in `plugins.txt` in the data folder (`#` starts a comment). The environment variable wins when both exist.

At startup Nazgarr installs them with pip into `<data_dir>/plugins/site`, so they survive container updates. pip only runs again when the list changes, and then it installs everything from scratch: a plugin you remove from the list is gone after the restart. **Restart the container after changing the list.**

Each line is a package (a name, `name==version`, or a `git+https://…` URL). Lines starting with `-` are refused: pip options such as `--index-url` could make it install packages from anyone's index. Only plugins installed there are loaded: a package with a `nazgarr.plugins` entry point installed anywhere else is ignored. Pin versions (`nazgarr-ntfy==0.3.1`) so an update never arrives by surprise.

**Settings > Plugins** shows:

- the plugins that were loaded, with their version and the adapters they add;
- the plugins that failed to install or load, or that need another SDK version, with the error. They stay off and the rest of Nazgarr works as usual;
- a form for the adapters that have no row of their own (image hosts, media resolvers, notifications): their fields, an on/off switch and, for notifications, the events to send and a test.

Tracker and torrent client adapters from plugins appear as new types in the "Add tracker" and "Add client" dialogs, with their own fields.

---

## Writing a plugin

A plugin is a normal Python package with an entry point in the `nazgarr.plugins` group. [`examples/nazgarr-ntfy`](../examples/nazgarr-ntfy) is a complete, working one: ntfy notifications.

```toml
# pyproject.toml
[project]
name = "nazgarr-ntfy"
version = "0.1.0"
dependencies = []          # httpx is already in Nazgarr

[project.entry-points."nazgarr.plugins"]
ntfy = "nazgarr_ntfy:setup"
```

```python
# nazgarr_ntfy/__init__.py
import nazgarr_sdk as sdk

REQUIRES_SDK = ">=1.0,<2"   # required: the SDK versions this plugin works with (PEP 440)


def setup() -> None:
    """Called once at startup: register your adapters."""
    sdk.register(sdk.AdapterSpec(
        kind="notification",
        adapter_type="ntfy",            # unique for its kind; stored in the database
        label="ntfy",                   # shown in the UI
        description="Push notifications through an ntfy server",
        config_fields=(
            sdk.ConfigField("server", "Server", type="url", default="https://ntfy.sh"),
            sdk.ConfigField("topic", "Topic", required=True),
            sdk.ConfigField("token", "Access token", type="secret"),
        ),
        build=lambda ctx: NtfyNotifier(ctx.config["server"], ctx.config["topic"], ctx.config.get("token")),
    ))
```

Import only from `nazgarr_sdk`, never from `app.*`: `nazgarr_sdk` is the stable contract, and the rest may change in any release. Dependencies you declare are installed next to your plugin. When a version conflicts with one Nazgarr ships, Nazgarr's version wins.

### `AdapterSpec`

| Field | Meaning |
|---|---|
| `kind` | `"tracker"`, `"torrent_client"`, `"media_resolver"`, `"image_host"` or `"notification"` |
| `adapter_type` | Unique name for this kind. A plugin cannot replace a built-in adapter (`qbittorrent`, `qui`, `unit3d`, the built-in image hosts). |
| `label`, `description` | What the UI shows |
| `config_fields` | The settings your adapter needs (below) |
| `build(ctx)` | Returns an instance of your adapter; called every time Nazgarr needs one |

### `ConfigField`

`ConfigField(key, label, type="text", required=False, default=None, help=None, choices=())`, where `type` is one of:

| Type | UI | Value your adapter gets |
|---|---|---|
| `text` | text input | `str` |
| `secret` | password input, never shown again | `str` |
| `url` | text input, must start with `http://` or `https://` | `str` |
| `number` | number input | `int` or `float` |
| `boolean` | switch | `bool` |
| `choice` | select among `choices` | `str` |

An adapter whose required fields are not all filled in is skipped, like a built-in image host without its API key.

### `AdapterContext`

`build` receives:

- `ctx.config`: the values of your fields (defaults filled in);
- `ctx.row`: for trackers and torrent clients, their database row (read only): `label`, `base_url`, and for trackers `api_token`, `announce_url`, `rss_key`;
- `ctx.session`: the database session. Use it to read, never to change files or clients.

### Where each kind is configured and used

| Kind | Configured | Used for |
|---|---|---|
| `tracker` | on the tracker, in Settings > Trackers | search, reseeding, uploads |
| `torrent_client` | on the client, in Settings > Clients | indexing torrents, reseeding, uploads |
| `media_resolver` | Settings > Plugins | recognizing files: plugin resolvers are tried **before** Radarr/Sonarr and TMDB, and the first that recognizes a file wins; they also work without a TMDB key |
| `image_host` | Settings > Plugins | upload screenshots: plugin hosts go at the end of the image host priority |
| `notification` | Settings > Plugins, with the events to send | the events below, as readable messages |

---

## Adapter contracts

Methods marked **required** are abstract. The others have a default that raises `NotSupportedError` or does nothing. The types (`TorrentCandidate`, `UploadFields`, `TorrentStatus`, `ClientTorrentInfo`, `ResolvedMedia`, `Notification`…) are all exported by `nazgarr_sdk`, with their fields documented in their docstrings.

### `TrackerAdapter`

| Method | |
|---|---|
| `search_by_tmdb(tmdb_id) -> list[TorrentCandidate]` | **required**: the tracker's torrents for a movie or series |
| `download_torrent(url) -> bytes` | a `.torrent` from a `download_link`, through the tracker's rate limit |
| `upload_torrent(fields: UploadFields, torrent_path) -> UploadedTorrent` | publish a new upload; return the tracker id and the link to download the `.torrent` **as the tracker stored it**, because trackers often rewrite it and the info hash changes |
| `get_own_history() -> list[TorrentRecord]` | your history on the tracker, if it has one |

Raise `UploadError` when the tracker refuses an upload, and `TrackerRateLimitedError` when it asks you to slow down.

### `TorrentClientAdapter`

| Method | |
|---|---|
| `list_torrents(on_progress=None) -> list[ClientTorrentInfo]` | **required**: every torrent with its files, read only |
| `add_torrent(torrent_file_or_url, save_path, force_recheck=True, expected_info_hash=None, skip_check_verified=False, category=None, tags=None) -> str` | **required**: add a torrent and return its info hash. Always recheck unless `skip_check_verified` is true (Nazgarr has just verified every piece itself). Never turn on the client's automatic torrent management: a category is only a label and must not move files. |
| `get_torrent_status(info_hash) -> TorrentStatus` | **required**: the state of a torrent and of its recheck |
| `get_torrent_info(info_hash) -> ClientTorrentInfo \| None` | one torrent with its files |
| `recheck(info_hash)` | ask the client to check a torrent again |
| `list_categories() -> list[str]` | the client's categories, for the category pickers |

Raise `TorrentAddTimeoutError` if the torrent never shows up after adding it, and `TorrentAlreadyInClientError` if the client already has it.

### `MediaResolverAdapter`

| Method | |
|---|---|
| `resolve(file_path) -> ResolvedMedia \| None` | **required**: what a file is (TMDB id, movie or series, season and episode). Return `None` when you don't know, and raise only for real errors. Set `SOURCE` to a short name. |

### `ImageHostAdapter`

| Method | |
|---|---|
| `upload(image_path) -> str` | **required**: upload a screenshot and return the URL of the **full-size image**, not a thumbnail or a page. Raise `ImageHostError` on failure, and Nazgarr tries the next host. |

### `NotificationAdapter`

| Method | |
|---|---|
| `send(notification: Notification)` | **required**: deliver the message. Raise an exception (e.g. `NotificationError`) on failure, and the delivery is retried like a webhook. |

`Notification` has `event`, `title`, `body` (plain text, may contain line breaks), `level` (`info`, `success`, `warning`, `error`) and `data` (the event payload, as in webhooks).

---

## Events

| Event | When | `data` |
|---|---|---|
| `run.finished` | a scan and matching run ends, also when stopped or with errors | `run_id`, `run_type`, `started_at`, `finished_at`, `errors`, `items_scanned`, `matches_found`, `auto_executed`, `pending_review`, `health_pct`, `stopped` |
| `review.created` | a match waits for review, or was approved automatically | `review_id`, `status` (`pending` \| `auto_approved`), `confidence`, `direction`, `media_file_id`, `seed_file_id`, `candidate_id`, `torrent`, `tracker`, `torrent_id_remote` |
| `review.decided` | a review is approved or rejected | `review_id`, `status`, `decided_by`, `candidate_id`, `torrent`, `tracker`, `torrent_id_remote` |
| `seed_job.finished` | a reseed is seeding, or failed | `seed_job_id`, `status` (`seeding` \| `failed`), `info_hash`, `error`, `recheck_skipped`, `candidate_id`, `torrent`, `tracker`, `torrent_id_remote` |
| `upload.finished` | an upload job ends | `job_id`, `status` (`done` \| `partial` \| `failed` \| `cancelled`), `title`, `year`, `content_type`, `tmdb_id`, `targets`: `[{tracker, action, status, torrent_id_remote, error}]` |
| `test` | "Send a test" | `message`, and `webhook` for webhooks |

Payloads only grow: fields are added in minor versions, never removed or renamed without a major version.

Events are written in the same database transaction as the change that causes them, and delivered afterwards, so a restart loses nothing. They are stored only when a webhook or a notification service subscribes to them, and kept 30 days.

---

## Webhooks

Configure them in **Settings > Webhooks**: a name, a URL and the events (all, or some). The secret used to sign them is shown once, after saving; "New secret" replaces it.

Every delivery is a `POST` with a JSON body:

```json
{"id": 128, "event": "seed_job.finished", "created_at": "2026-09-30T18:04:11+00:00", "data": {"...": "..."}}
```

and these headers:

| Header | |
|---|---|
| `X-Nazgarr-Event` | the event name |
| `X-Nazgarr-Delivery` | the delivery id, the same on every retry: use it to ignore duplicates |
| `X-Nazgarr-Timestamp` | Unix seconds of this attempt |
| `X-Nazgarr-Signature` | `sha256=` + HMAC-SHA256 of the secret over `"<timestamp>.<raw body>"` |

Verify the signature on the raw body, and reject old timestamps to block replays:

```python
import hashlib, hmac, time

def verify(secret: str, headers, raw_body: bytes, max_age: int = 300) -> bool:
    timestamp = headers["X-Nazgarr-Timestamp"]
    if abs(time.time() - int(timestamp)) > max_age:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(headers["X-Nazgarr-Signature"], f"sha256={expected}")
```

A `2xx` answer (within 10 seconds) is a success. Anything else is retried after 1 minute, 5 minutes, 30 minutes, 2 hours and 6 hours; after that the delivery is marked failed. Redirects are not followed. "Deliveries" shows the last 50 for each webhook, with the answer or the error.

---

## API keys

Create them in **Settings > Security > API keys**. A key is shown once and Nazgarr keeps only its SHA-256 hash. Send it in the `X-Api-Key` header:

```sh
curl -H "X-Api-Key: nzg_..." http://nazgarr:8080/api/dashboard
```

| Level | Can |
|---|---|
| read | every `GET`: libraries, torrents, dashboard, history, settings (without secrets) |
| write | everything you can do after logging in: create upload jobs, approve reviews, change settings |

**What no key can do**, whatever its level:

- manage API keys: creating or revoking them requires the real login, so a stolen key cannot create more keys to stay in;
- read or change secret settings (API keys, tokens, passwords) or the login's own settings;
- change the safety settings (verification before executing, the client's recheck, automatic execution and its thresholds);
- move a tracker, client or Radarr/Sonarr instance to another host without sending its secrets again in the same request, so a changed address can never receive the saved token.

A wrong or revoked key always gets `401`; a read key gets `403` on anything but `GET`. Error messages returned by the API never contain credentials (download keys, passkeys, tokens in URLs).

The full API is described at `/docs` (OpenAPI) on your instance.
