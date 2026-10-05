# Nazgarr SDK: plugins, webhooks and API keys

Nazgarr can be extended in three ways:

- **Plugins**: Python packages that add adapters, such as a tracker, a torrent client, a media resolver, an image host or a notification service.
- **Webhooks**: signed HTTP calls for the events you choose.
- **API keys**: scripts and other services can use the same JSON API as the web UI.

SDK version: **1.2.0** (`nazgarr.sdk.SDK_VERSION`, [semantic versioning](https://semver.org): a breaking change bumps the major version). 1.1 added `AdapterSpec.icon`, 1.2 `CheveretoImageHost` and `chevereto_image_url`: a plugin that uses them needs `REQUIRES_SDK = ">=1.1,<2"` or `">=1.2,<2"`.

## Rules that apply to everything here

- **Nothing changes files or torrent clients without your approval.** A plugin, an API key or a webhook receiver can only *propose* a change (a review, an upload job); the change runs after you approve it, as it does from the UI.
- **Plugins run inside Nazgarr with its permissions.** They can read the database and your files. Install only plugins you trust.
- **Secrets never come back.** Configuration fields marked as secret are stored encrypted and the API only says whether they are set. The same goes for API keys and webhook secrets, which are shown once.

---

## Installing plugins

List the pip packages in the `NAZGARR_PLUGINS` environment variable, separated by spaces or commas:

```yaml
environment:
  - NAZGARR_PLUGINS=nazgarr-flood nazgarr-ntfy==0.3.1 git+https://github.com/you/nazgarr-thing
```

Or write them one per line in `plugins.txt` in the data folder (`#` starts a comment). The environment variable wins when both exist.

At startup Nazgarr installs them with pip into `<data_dir>/plugins/site`, so they survive container updates. pip only runs again when the list changes (or, for a plugin listed as a local folder, when its code changes), and then it installs everything from scratch: a plugin you remove from the list is gone after the restart. **Restart the container after changing the list.**

Each line is a package (a name, `name==version`, or a `git+https://…` URL). Lines starting with `-` are refused: pip options such as `--index-url` could make it install packages from anyone's index. Only plugins installed there are loaded: a package with a `nazgarr.plugins` entry point installed anywhere else is ignored. Pin versions (`nazgarr-ntfy==0.3.1`) so an update never arrives by surprise.

**Settings > Extensions > Plugins** shows:

- the plugins that were loaded, with their version and the adapters they add;
- one card per plugin, like a browser's extensions: its name, an on/off switch, where it comes from (native, shipped with Nazgarr, or installed), its category and, for the image hosts and media resolvers that have no row of their own, a Settings button with their fields;
- the plugins that failed to install or load, or that need another SDK version, with the error. They stay off and the rest of Nazgarr works as usual.

Native plugins, one per image host (`nazgarr-ptscreens`, `nazgarr-passtheima`, `nazgarr-imageride`, `nazgarr-imgbb`), are written like any plugin but shipped in the image, without installing anything. Switching a plugin off, native or installed, takes effect at once, without a restart: its adapters leave the registry (an image host leaves the chain, a tracker or client type can no longer be used) and come back when it is switched on again, through its `setup()`. The choice survives restarts.

Image hosts, bundled or from a plugin, are all configured in **Settings > Upload > Images**: one list in priority order, with an on/off switch and the API key of each.

Notification services from plugins appear under **Settings > Extensions > Notifications**, next to the built-in Discord and Telegram and the webhooks: "Add" lists every type, and each instance (there can be several per type, such as two ntfy topics) is a card with its own fields, events and a test.

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
import nazgarr.sdk as sdk

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

Import only from `nazgarr.sdk`, never from the rest of `nazgarr`: `nazgarr.sdk` is the stable contract, and the rest may change in any release. Dependencies you declare are installed next to your plugin. When a version conflicts with one Nazgarr ships, Nazgarr's version wins.

### `AdapterSpec`

| Field | Meaning |
|---|---|
| `kind` | `"tracker"`, `"torrent_client"`, `"media_resolver"`, `"image_host"` or `"notification"` |
| `adapter_type` | Unique name for this kind. A plugin cannot replace a built-in adapter (`qbittorrent`, `qui`, `unit3d`) or one of a native plugin (the image hosts `ptscreens`, `passtheima`, `imageride`, `imgbb`). |
| `label`, `description` | What the UI shows |
| `icon` | Optional (SDK 1.1): an image as a `data:image/...` URI (a small SVG or PNG, at most 64 KB), shown next to the label. Built-in adapters have their own. |
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

An adapter whose required fields are not all filled in is skipped, like an image host without its API key.

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
| `media_resolver` | Settings > Extensions > Plugins | recognizing files: plugin resolvers are tried **before** Radarr/Sonarr and TMDB, and the first that recognizes a file wins; they also work without a TMDB key |
| `image_host` | Settings > Upload > Images, with the native hosts (or the plugin's Settings button) | upload screenshots: a new host joins the end of the priority list, and the user can move it or switch it off |
| `notification` | Settings > Extensions > Notifications: any number of instances, each with its fields and the events to send | the events below, as readable messages |

---

## Adapter contracts

Methods marked **required** are abstract. The others have a default that raises `NotSupportedError` or does nothing. The types (`TorrentCandidate`, `UploadFields`, `TorrentStatus`, `ClientTorrentInfo`, `ResolvedMedia`, `Notification`…) are all exported by `nazgarr.sdk`, with their fields documented in their docstrings.

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
| `add_torrent(torrent_file_or_url, save_path, force_recheck=True, expected_info_hash=None, skip_check_verified=False, category=None, tags=None, content_layout="Original") -> str` | **required**: add a torrent and return its info hash. Always recheck unless `skip_check_verified` is true (Nazgarr has just verified every piece itself). Never turn on the client's automatic torrent management: a category is only a label and must not move files. `content_layout` (`Original`, `Subfolder`, `NoSubfolder`) overrides the client's own layout preference for this torrent; a client without such a preference can ignore it. |
| `get_torrent_status(info_hash) -> TorrentStatus` | **required**: the state of a torrent and of its recheck |
| `get_torrent_info(info_hash) -> ClientTorrentInfo \| None` | one torrent with its files. Also asked after a failed add, to know whether the torrent reached the client anyway: return `None` only when the client really does not have it |
| `content_layout() -> str` | the user's layout preference for added torrents (default `Original`): reseeds place their new hardlinks to match it |
| `recheck(info_hash)` | ask the client to check a torrent again |
| `list_categories() -> list[str]` | the client's categories, for the category pickers |
| `remove_torrent(info_hash, delete_files)` | remove a torrent from the client; with `delete_files`, also its files (only the torrent's own). Only called on an explicit user request |

Raise `TorrentAddTimeoutError` if the torrent never shows up after adding it, and `TorrentAlreadyInClientError` if the client already has it.

When `torrent_file_or_url` is a local file, send its **content** to the client, never its path: the client usually runs in another container and cannot see Nazgarr's data folder. Only real URLs (http, https, magnet) go to the client as URLs.

Set the class attribute `can_skip_recheck = False` if the client cannot add a torrent as already complete: Nazgarr then never records a skipped recheck for it, and `add_torrent` rechecks even when `skip_check_verified` is true.

### `MediaResolverAdapter`

| Method | |
|---|---|
| `resolve(file_path) -> ResolvedMedia \| None` | **required**: what a file is (TMDB id, movie or series, season and episode). Return `None` when you don't know, and raise only for real errors. Set `SOURCE` to a short name. |

### `ImageHostAdapter`

| Method | |
|---|---|
| `upload(image_path) -> str` | **required**: upload a screenshot and return the URL of the **full-size image**, not a thumbnail or a page. Raise `ImageHostError` on failure, and Nazgarr tries the next host. |

Many image hosts run [Chevereto](https://chevereto.com), with the same API: `POST <site>/api/1/upload`, the key in the `X-API-Key` header, the file in the `source` field. For those, SDK 1.2 has `CheveretoImageHost(api_key, endpoint=..., name=...)`, a complete adapter, and `chevereto_image_url(response)`, which reads the image URL from the slightly different answers of each site. A plugin for a Chevereto host is then just its registration:

```python
import nazgarr.sdk as sdk

REQUIRES_SDK = ">=1.2,<2"


def setup():
    sdk.register(sdk.AdapterSpec(
        "image_host", "myhost", "My host",
        lambda ctx: sdk.CheveretoImageHost(ctx.config["api_key"], endpoint="https://myhost.example/api/1/upload",
                                           name="My host"),
        config_fields=(sdk.ConfigField("api_key", "API key", type="secret", required=True),),
    ))
```

[`examples/nazgarr-lensdump`](../examples/nazgarr-lensdump) is a complete one: Lensdump's API is paid, so it is not bundled.

### `NotificationAdapter`

| Method | |
|---|---|
| `send(notification: Notification)` | **required**: deliver the message. Raise an exception (e.g. `NotificationError`) on failure, and the delivery is retried like a webhook. |

`Notification` has `event`, `title`, `body` (plain text, may contain line breaks), `level` (`info`, `success`, `warning`, `error`) and `data` (the event payload, as in webhooks).

---

## Developing a plugin step by step

### 1. Set up a development copy of Nazgarr

`nazgarr.sdk` lives in the Nazgarr repository, and your plugin's tests import it, so develop against a checkout:

```sh
git clone https://github.com/lktorrentz/nazgarr && cd nazgarr
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt && ./.venv/bin/pip install -r requirements-dev.txt
```

Keep your plugin in its own folder or repository next to it:

```
nazgarr-myclient/
├── pyproject.toml
├── nazgarr_myclient/
│   └── __init__.py      # REQUIRES_SDK, setup(), the adapter
└── tests/
    └── test_myclient.py
```

Run the plugin's tests with Nazgarr on the path:

```sh
PYTHONPATH=/path/to/nazgarr /path/to/nazgarr/.venv/bin/python -m pytest tests
```

### 2. Write the adapter, and make its network calls injectable

Pass the HTTP client in the constructor (with a real one as the default). Your tests can then use `httpx.MockTransport` instead of a real tracker or client, as the ntfy example does:

```python
class NtfyNotifier(sdk.NotificationAdapter):
    def __init__(self, server, topic, token=None, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=10.0)
```

#### A torrent client, minimal

```python
import httpx
import nazgarr.sdk as sdk

REQUIRES_SDK = ">=1.0,<2"

# Your client's states -> the names Nazgarr reads (table below).
STATES = {"seeding": "uploading", "paused": "stoppedUP", "checking": "checkingUP", "downloading": "downloading"}


class MyClient(sdk.TorrentClientAdapter):
    def __init__(self, base_url: str, token: str, client: httpx.Client | None = None):
        self.http = client or httpx.Client(base_url=base_url, timeout=30.0, headers={"Authorization": token})

    def list_torrents(self, on_progress=None) -> list[sdk.ClientTorrentInfo]:
        torrents = self.http.get("/torrents").json()
        return [
            sdk.ClientTorrentInfo(
                info_hash=t["hash"], name=t["name"], save_path=t["path"], state=STATES.get(t["status"], "error"),
                category=t.get("label"), tracker_url=t.get("tracker"),
                files=[sdk.ClientTorrentFileInfo(path_in_torrent=f["path"], size_bytes=f["size"]) for f in t["files"]],
            )
            for t in torrents
        ]

    def add_torrent(self, torrent_file_or_url, save_path, force_recheck=True, expected_info_hash=None,
                    skip_check_verified=False, category=None, tags=None) -> str:
        ...  # add it at save_path, recheck unless skip_check_verified, return the info hash

    def get_torrent_status(self, info_hash) -> sdk.TorrentStatus:
        t = self.http.get(f"/torrents/{info_hash}").json()
        state = STATES.get(t["status"], "error")
        recheck = "pending" if state.startswith("checking") else "failed" if state == "error" else "ok"
        return sdk.TorrentStatus(info_hash=info_hash, state=state, recheck_status=recheck, progress=t["progress"])


def setup() -> None:
    sdk.register(sdk.AdapterSpec(
        kind="torrent_client", adapter_type="myclient", label="My client",
        config_fields=(sdk.ConfigField("token", "API token", type="secret", required=True),),
        build=lambda ctx: MyClient(ctx.row.base_url, ctx.config["token"]),
    ))
```

**States**: Nazgarr reads torrent states with qBittorrent's names, so map your client's states to them:

| State | Meaning |
|---|---|
| `uploading`, `stalledUP`, `forcedUP`, `queuedUP` | complete, seeding |
| `pausedUP` / `stoppedUP` (anything starting with `paused` or `stopped`) | complete, stopped |
| `checkingUP`, `checkingDL`, `checkingResumeData` | being rechecked |
| `downloading`, `stalledDL`, `metaDL` | incomplete |
| `error`, `missingFiles` | the client can't read the data |

The client's base URL is a column of every client (`ctx.row.base_url`). Only your extra settings go in `config_fields`.

#### A tracker, minimal

```python
class MyTracker(sdk.TrackerAdapter):
    def __init__(self, base_url: str, api_token: str, client: httpx.Client | None = None):
        self.http = client or httpx.Client(base_url=base_url, timeout=30.0)
        self.api_token = api_token

    def search_by_tmdb(self, tmdb_id: int) -> list[sdk.TorrentCandidate]:
        results = self.http.get("/api/search", params={"tmdb": tmdb_id, "key": self.api_token}).json()
        return [
            sdk.TorrentCandidate(
                torrent_id_remote=str(r["id"]), info_hash=r.get("infohash"), name=r["name"], size_bytes=r["size"],
                file_list=[f["name"] for f in r["files"]], mediainfo_unique_id=None,
                folder=r.get("folder"), download_link=r["download"],
                file_sizes={f["name"]: f["size"] for f in r["files"]},
            )
            for r in results
        ]

    def download_torrent(self, url: str) -> bytes:
        response = self.http.get(url)
        response.raise_for_status()
        return response.content


def setup() -> None:
    sdk.register(sdk.AdapterSpec(
        kind="tracker", adapter_type="mytracker", label="My tracker",
        build=lambda ctx: MyTracker(ctx.row.base_url, ctx.row.api_token),
    ))
```

Every tracker has `base_url`, `api_token`, `announce_url` and `rss_key` as columns (`ctx.row`), so most trackers need no `config_fields` at all. A tracker's `.torrent` files are untrusted: Nazgarr validates the paths inside them itself, so pass the bytes through unchanged.

### 3. Test it with fakes

```python
import httpx
import nazgarr.sdk as sdk
from nazgarr.plugins import REGISTRY      # tests only: your plugin code imports nazgarr.sdk alone

import nazgarr_myclient


def test_setup_registers_the_client():
    nazgarr_myclient.setup()
    spec = REGISTRY.get("torrent_client", "myclient")
    assert spec.label == "My client"
    REGISTRY.unregister("torrent_client", "myclient")


def test_list_torrents_maps_the_states():
    def handler(request):
        return httpx.Response(200, json=[{"hash": "abc", "name": "x", "path": "/data", "status": "seeding",
                                          "files": [{"path": "x.mkv", "size": 1}]}])

    client = httpx.Client(base_url="http://myclient", transport=httpx.MockTransport(handler))
    [torrent] = nazgarr_myclient.MyClient("http://myclient", "t", client=client).list_torrents()
    assert torrent.state == "uploading"
```

Unregister what your tests register, or the next test that registers the same type fails with `AdapterAlreadyRegisteredError`.

### 4. Try it in Nazgarr

Add the plugin to the list as a path, then restart:

- **Running Nazgarr from source**: put the absolute path of the plugin folder in `<data_dir>/plugins.txt`.
- **In Docker**: mount the folder (for example `- ./nazgarr-myclient:/plugins/nazgarr-myclient`) and list `/plugins/nazgarr-myclient`. Mount it read-write: pip builds a local package inside its own folder (`build/`, `*.egg-info`, which you can gitignore).

A plugin listed as a local folder is reinstalled at the next restart whenever its code changes: Nazgarr compares the folder's files (names, sizes, modification times) with the last install, ignoring `build/`, `*.egg-info`, `__pycache__`, `.git` and virtual environments. So the loop is: edit, restart, check. When nothing changed, pip doesn't run.

Then check **Settings > Extensions > Plugins**:

If pip fails, nothing new is installed and the page shows **Installing the plugins failed** with pip's own output (the log has it too). Otherwise each plugin has a status:

| Status | What to do |
|---|---|
| `loaded` | it works: its adapters are listed, and a client or tracker type appears in the "Add" dialogs |
| `failed` | `setup()` or the import raised: the error is shown, the full traceback is in the log (`Plugin <name> non caricato`) |
| `incompatible` | `REQUIRES_SDK` is missing or doesn't include this Nazgarr's SDK version |

A plugin that fails never registers anything, and the rest of Nazgarr works as usual.

### 5. Publish it

- Name the package `nazgarr-<something>` and the module `nazgarr_<something>`, so people can recognize plugins.
- Publish it on PyPI, or just in a git repository: users can list `git+https://github.com/you/nazgarr-myclient@v1.0.0`.
- Tell users to pin a version (`nazgarr-myclient==1.0.0`), so an update only arrives when they choose it.
- Declare the SDK range you tested with: `REQUIRES_SDK = ">=1.0,<2"`. A new minor SDK version only adds things, so `<2` is safe; a new major version may break your plugin, and Nazgarr won't load it until you update the range.
- Keep secrets in `secret` fields: Nazgarr encrypts them and never returns them. Never log them yourself, and never put them in exception messages: errors are shown in the UI.

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

Configure them in **Settings > Extensions > Webhooks**: a name, a URL and the events (all, or some). The secret used to sign them is shown once, after saving; "New secret" replaces it.

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

Create them in **Settings > Extensions > API keys**. A key is shown once and Nazgarr keeps only its SHA-256 hash. Send it in the `X-Api-Key` header:

```sh
curl -H "X-Api-Key: nzg_..." http://nazgarr:3019/api/dashboard
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
