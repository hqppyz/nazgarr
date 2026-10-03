# Nazgarr from the command line

The `nazgarr` command does two jobs:

- **Server commands** (`init`, `serve`, `install-service`, `version`) run Nazgarr on this machine. They are described in the README, under "Python package".
- **Client commands** (everything else) talk to a running Nazgarr through its JSON API, the same one the web UI uses. They work on the machine that runs Nazgarr, from another computer, and inside the Docker container.

Every command has its own help: `nazgarr --help`, `nazgarr review --help`, `nazgarr review approve --help`.

The rule of the web UI still holds: **nothing that touches your files or your torrent clients runs without your confirmation.** These commands ask before acting:

- approving a review;
- retrying an execution;
- cancelling a scan.

In a script, add `--yes` to confirm without a prompt. Without a terminal and without `--yes`, they stop with exit code 3.

## Install

- **With the Python package** (`pipx install nazgarr`), the command is already there. It can also be installed only to talk to an instance running elsewhere.
- **In the Docker container**, run the command inside it:

  ```bash
  docker exec -it nazgarr nazgarr login
  docker exec -it nazgarr nazgarr status
  ```

  Inside the container the address is already set (`NAZGARR_URL=http://127.0.0.1:8080`). The login is kept in the config folder (`/app/config/cli.toml`), so it survives updates.

## Connect

### A fresh installation

```bash
nazgarr setup --url http://nas:8080
```

The command asks for:

- **the one-time setup code**, printed in the log at the first start (`docker logs nazgarr`, or the service log);
- **a username and a password.**

It then creates the account and logs in, the same way the web UI does.

### An existing installation

```bash
nazgarr login --url http://nas:8080
```

The password is used once. With it, the CLI creates a dedicated API key named `cli-HOSTNAME`, with write access unless you pass `--read-only`.

The CLI keeps only that key, in a file readable by you alone:

- **Linux:** `~/.config/nazgarr/cli.toml`
- **macOS:** `~/Library/Application Support/Nazgarr/cli.toml`

Passwords are always asked on screen, never passed as arguments. Arguments would end up in your shell history and in `ps`. In a script, pipe the password with `--password-stdin`:

```bash
printf '%s\n' "$NAZGARR_PASSWORD" | nazgarr login --url http://nas:8080 -u admin --password-stdin
```

### More instances

Each login saves a **profile**. The first one is called `default`.

```bash
nazgarr --profile seedbox login --url https://seedbox.example:8080
nazgarr profile ls            # the saved instances, * marks the default
nazgarr profile use seedbox   # make it the default
nazgarr -P default status     # one command on another profile
```

### Log out

```bash
nazgarr logout            # forget the key on this computer
nazgarr logout --revoke   # and revoke it on the server (asks the password)
```

A key can also be revoked in the web UI, under Settings › Extensions › API keys.

### Environment variables

They override the saved profile. Useful for cron jobs and containers:

| Variable | Meaning |
| --- | --- |
| `NAZGARR_URL` | Address of the instance |
| `NAZGARR_API_KEY` | API key to use (create one in the web UI or with `nazgarr login`) |
| `NAZGARR_PROFILE` | Saved profile to use |
| `NAZGARR_CLI_CONFIG` | Path of the profiles file |

## Global options

| Option | Meaning |
| --- | --- |
| `--profile`, `-P` | Saved instance to use |
| `--url` | Address of the instance, overriding the profile |
| `--json` | Print the raw JSON answer, for scripts and `jq` |
| `--install-completion` | Install tab completion for your shell (bash, zsh, fish, PowerShell) |

Global options go **before** the command: `nazgarr --json review ls`.

## Commands

### Overview

```bash
nazgarr status
```

Shows, at a glance:

- the version;
- the setup checklist;
- the library health;
- the counts of orphaned torrents, triage and duplicates;
- the reviews waiting;
- the last scan;
- the uploads in progress.

### Scans

```bash
nazgarr scan                 # start a scan and return
nazgarr scan --wait          # follow it with a progress bar until it ends
nazgarr runs ls -n 20        # the latest scans
nazgarr runs show 42 -f      # one scan, following it while it runs
nazgarr runs cancel 42       # stop it (what it already saved stays)
```

A scan only reads: nothing is linked, added or moved. Its matches wait in the review queue.

If you press Ctrl+C during `scan --wait`, only the CLI stops following: the scan keeps running on the server.

### Reseeding review queue

```bash
nazgarr review ls                  # the proposals waiting for you
nazgarr review show 17             # one proposal
nazgarr review approve 17 18       # approve: hardlinks + torrent added to the client (asks first)
nazgarr review reject 19           # reject: nothing is touched
nazgarr review failed              # executions that failed
nazgarr review retry 7             # retry one (asks first)
```

With the full check on (the default), an approval first reads every piece of the torrent against your files. The hardlinks and the torrent follow only if the check passes.

### Any other endpoint

The raw API covers everything that has no command of its own yet. It works like `gh api`:

```bash
nazgarr api GET /api/dashboard
nazgarr api GET /api/library/items -p content_type=tv
nazgarr api POST /api/disks -d '{"label": "main", "root_path": "/data"}'
nazgarr api PATCH /api/trackers/3 -d @tracker.json
```

The full list of endpoints, with the exact request and answer of each, is at `http://HOST:8080/docs`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Done |
| 1 | Error, for example a request refused by the server, with its reason |
| 2 | Wrong usage, for example a missing option |
| 3 | Confirmation declined, or needed with `--yes` |
| 4 | Not logged in, wrong key, or a read-only key used for a change |

Error messages are the same as in the web UI, in English.

## Coming next

These command groups follow the same pattern and are planned next. Until they arrive, `nazgarr api` reaches the same endpoints.

| Group | What it will do |
| --- | --- |
| `disk` | Add disks and their media and seeding folders, test them |
| `client` | Add torrent clients, test them, link them to disks, set default labels |
| `tracker` | Add trackers (with presets), and edit their upload profile: flags, IDs, naming, description template |
| `arr` | Add Radarr and Sonarr instances |
| `settings`, `schedule` | Every setting of the web UI, and the scan schedule |
| `config export` / `config import` | The whole configuration as a YAML file, applied back after showing the differences. It only adds and updates, and secrets stay out of the file. |
| `upload` | The upload flow in the terminal, with match, decision and confirmation, including packs |
| `library`, `triage`, `logs` | Browse the library, the triage and the logs |
