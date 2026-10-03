"""nazgarr config export / import: tutta la configurazione in un file YAML.

L'import aggiunge e aggiorna, non toglie mai niente (decisione dell'utente,
2026-10-03): un disco, un client o un tracker che il file non nomina resta
com'è. Prima mostra il piano, poi chiede conferma (--yes per gli script,
--dry-run solo il piano).

I segreti non finiscono mai nel file: l'export scrive al loro posto un
segnaposto ${NAZGARR_…}, che l'import risolve dalle variabili d'ambiente.
Un segnaposto senza variabile: chiesto a schermo se serve per creare
qualcosa, ignorato (il valore sul server resta) se è un aggiornamento.
Le impostazioni di sicurezza e i segreti chiedono la password una volta sola."""

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer
import yaml

from nazgarr.cli_client import settings_catalog as catalog
from nazgarr.cli_client.context import api
from nazgarr.cli_client.helpers import duration, env_secret, human_duration, login_api
from nazgarr.cli_client.output import EXIT_USAGE, confirm, console, err_console, fail

app = typer.Typer(help="The whole configuration as a YAML file: export, then import (adds and updates).",
                  no_args_is_help=True)
VERSION = 1


def _placeholder(*parts: str) -> str:
    name = "_".join(re.sub(r"[^A-Za-z0-9]+", "_", p).strip("_").upper() for p in ("NAZGARR", *parts))
    return "${" + name + "}"


# --- export -------------------------------------------------------------------


def export_data(client) -> dict:
    disks = client.get("/api/disks")
    disk_label = {d["id"]: d["label"] for d in disks}
    clients = client.get("/api/torrent-clients")
    client_label = {c["id"]: c["label"] for c in clients}
    out: dict = {"version": VERSION}
    out["disks"] = [{
        "label": d["label"], "root_path": d["root_path"],
        "seeding_folders": d.get("seeding_folders") or [], "media_folders": d.get("media_folders") or [],
        "new_hardlinks_folder": d.get("new_torrent_rel_path"), "uploads_folder": d.get("upload_rel_path"),
        "watched_folder": d.get("watch_rel_path"),
    } for d in disks]
    out["torrent_clients"] = [{
        "label": c["label"], "type": c["adapter_type"], "url": c["base_url"], "enabled": c["enabled"],
        **({"username": c["username"], "password": _placeholder("CLIENT", c["label"], "PASSWORD")}
           if c.get("username") else {}),
        **({"qui_instance": c["qui_instance_id"], "api_token": _placeholder("CLIENT", c["label"], "TOKEN")}
           if c["adapter_type"] == "qui" else {}),
        "categories": {"movie": c.get("category_movie"), "tv": c.get("category_tv"),
                       "anime": c.get("category_anime")},
        "tags": {"upload": c.get("tags_upload"), "reseed": c.get("tags_reseed")},
        "disks": [{"disk": disk_label.get(a["disk_id"], a["disk_id"]), "client_root": a.get("torrent_client_root_path"),
                   "folder": a.get("local_rel_path")} for a in c["disks"]],
    } for c in clients]
    trackers = []
    for t in client.get("/api/trackers"):
        entry = {
            "label": t["label"], "type": t["adapter_type"], "url": t["base_url"], "enabled": t["enabled"],
            "api_token": _placeholder("TRACKER", t["label"], "TOKEN"),
            "language": t.get("language"), "client": client_label.get(t.get("torrent_client_id")),
            "min_seed_time": human_duration(t.get("min_seed_time_seconds")) or None,
            "min_ratio": t.get("min_ratio"), "seed_rule": t.get("seed_rule"),
            "rate_limit": t.get("rate_limit_per_min"),
        }
        if t.get("has_announce_url"):
            entry["announce_url"] = _placeholder("TRACKER", t["label"], "ANNOUNCE")
        if t.get("upload_profile"):
            p = client.get(f"/api/trackers/{t['id']}/upload-profile")
            entry["upload_profile"] = {
                "preset": p.get("source_profile_key"),
                "defaults": {"anonymous": p["default_anonymous"], "personal_release": p["default_personal_release"],
                             "internal": p.get("default_internal", False), "freeleech": p.get("default_freeleech")},
                "freeleech_options": p.get("freeleech_options") or [],
                "category_ids": p["category_id_map"], "type_ids": p["type_id_map"],
                "resolution_ids": p["resolution_id_map"],
                "naming_rules": p.get("naming_rules") if p.get("naming_customized") else None,
                "description_template": p.get("description_template"),
            }
        trackers.append(entry)
    out["trackers"] = trackers
    out["arr"] = {kind: [{"label": i["label"], "url": i["base_url"], "enabled": i["enabled"],
                          "priority": i["priority"], "api_key": _placeholder(kind, i["label"], "API_KEY")}
                         for i in client.get(f"/api/{kind}-instances")] for kind in ("radarr", "sonarr")}
    settings = {}
    for entry in catalog.CATALOG:
        if entry.kind == "secret":
            continue
        value = client.get(f"/api/settings/{entry.key}").get("value")
        if value not in (None, ""):
            settings[entry.key] = value
    out["settings"] = settings
    schedule = client.get("/api/schedule")
    out["schedule"] = schedule["cron"] if schedule["enabled"] else "off"
    return out


@app.command("export")
def export(ctx: typer.Context, output: Path = typer.Option(None, "--output", "-o", help="Write to a file.")):
    """Print the configuration as YAML (secrets as ${NAZGARR_…} placeholders)."""
    text = ("# Nazgarr configuration (nazgarr config import). Secrets are ${…} placeholders:\n"
            "# set those environment variables before importing, or you will be asked.\n"
            + yaml.safe_dump(export_data(api(ctx)), sort_keys=False, allow_unicode=True))
    if output:
        output.write_text(text)
        err_console.print(f"Written to {output}.")
    else:
        sys.stdout.write(text)


# --- import -------------------------------------------------------------------


@dataclass
class Step:
    text: str
    apply: Callable[[], object]
    privileged: bool = False


class Planner:
    def __init__(self, client):
        self.client = client
        self.steps: list[Step] = []
        self.login = None

    def add(self, text: str, apply: Callable[[], object], privileged: bool = False) -> None:
        self.steps.append(Step(text, apply, privileged))


def _secret_for_create(value, what: str) -> str | None:
    resolved = env_secret(value)
    if resolved:
        return resolved
    if value and sys.stdin.isatty():
        return typer.prompt(f"{what} (not in the environment)", hide_input=True)
    return None


def _changed(current: dict, wanted: dict) -> dict:
    return {k: v for k, v in wanted.items() if v is not None and current.get(k) != v}


def _plan_disks(plan: Planner, wanted: list[dict]) -> dict[str, int | None]:
    client = plan.client
    current = {d["label"].lower(): d for d in client.get("/api/disks")}
    ids: dict[str, int | None] = {label: d["id"] for label, d in current.items()}
    for spec in wanted or []:
        label = spec["label"]
        disk = current.get(label.lower())
        if disk is None:
            holder: dict = {}

            def create(spec=spec, holder=holder):
                holder.update(client.post("/api/disks", {"label": spec["label"], "root_path": spec["root_path"]}))
                ids[spec["label"].lower()] = holder["id"]
            plan.add(f"+ disk {label} ({spec['root_path']})", create)
            disk_ref: Callable[[], int] = lambda holder=holder: holder["id"]  # noqa: E731
            existing_folders: set = set()
        else:
            disk_ref = lambda disk=disk: disk["id"]  # noqa: E731
            existing_folders = {(f["kind"], f["relative_path"]) for f in disk.get("folders") or []}
        for kind, key in (("seeding", "seeding_folders"), ("media", "media_folders")):
            for path in spec.get(key) or []:
                if (kind, path) not in existing_folders:
                    plan.add(f"+ {kind} folder {label}:{path}", lambda kind=kind, path=path, ref=disk_ref: client.post(
                        f"/api/disks/{ref()}/folders", {"kind": kind, "relative_path": path}))
        patch = {"new_torrent_rel_path": spec.get("new_hardlinks_folder"),
                 "upload_rel_path": spec.get("uploads_folder"), "watch_rel_path": spec.get("watched_folder")}
        changes = _changed(disk or {}, patch)
        if changes:
            plan.add(f"~ disk {label}: {', '.join(changes)}",
                     lambda changes=changes, ref=disk_ref: client.patch(f"/api/disks/{ref()}", changes))
    return ids


def _plan_clients(plan: Planner, wanted: list[dict], disk_ids: dict) -> dict[str, int | None]:
    client = plan.client
    current = {c["label"].lower(): c for c in client.get("/api/torrent-clients")}
    ids: dict[str, int | None] = {label: c["id"] for label, c in current.items()}
    for spec in wanted or []:
        label = spec["label"]
        found = current.get(label.lower())
        categories, tags = spec.get("categories") or {}, spec.get("tags") or {}
        fields = {"base_url": spec.get("url"), "username": spec.get("username"), "enabled": spec.get("enabled"),
                  "qui_instance_id": spec.get("qui_instance"), "category_movie": categories.get("movie"),
                  "category_tv": categories.get("tv"), "category_anime": categories.get("anime"),
                  "tags_upload": tags.get("upload"), "tags_reseed": tags.get("reseed")}
        if found is None:
            holder: dict = {}
            body = {"label": label, "adapter_type": spec.get("type", "qbittorrent"), "base_url": spec["url"],
                    "username": spec.get("username"), "qui_instance_id": spec.get("qui_instance")}
            if spec.get("password"):
                body["password"] = _secret_for_create(spec["password"], f"Password of client {label}")
            if spec.get("api_token"):
                body["api_token"] = _secret_for_create(spec["api_token"], f"API token of client {label}")
            extra = {k: v for k, v in fields.items() if k not in body and v is not None}

            def create(body=body, extra=extra, holder=holder, label=label):
                holder.update(client.post("/api/torrent-clients", {k: v for k, v in body.items() if v is not None}))
                ids[label.lower()] = holder["id"]
                if extra:
                    client.patch(f"/api/torrent-clients/{holder['id']}", extra)
            plan.add(f"+ client {label} ({spec['url']})", create)
            ref: Callable[[], int] = lambda holder=holder: holder["id"]  # noqa: E731
            linked: set = set()
        else:
            ref = lambda found=found: found["id"]  # noqa: E731
            linked = {a["disk_id"] for a in found["disks"]}
            mapping_now = {a["disk_id"]: (a.get("torrent_client_root_path"), a.get("local_rel_path"))
                           for a in found["disks"]}
            changes = _changed(found, fields)
            for key, name in (("password", "password"), ("api_token", "api_token")):
                resolved = env_secret(spec.get(key)) if spec.get(key) else None
                if resolved:
                    changes[name] = resolved
            if changes:
                shown = [k for k in changes if k not in ("password", "api_token")] + \
                        [f"{k} (from env)" for k in changes if k in ("password", "api_token")]
                plan.add(f"~ client {label}: {', '.join(shown)}",
                         lambda changes=changes, ref=ref: client.patch(f"/api/torrent-clients/{ref()}", changes))
        for link in spec.get("disks") or []:
            disk_name = str(link["disk"]).lower()
            if disk_name not in disk_ids:
                raise fail(f"Client {label} links disk {link['disk']!r}, which is neither in the file nor on the "
                           "server.", EXIT_USAGE)
            body = {k: v for k, v in {"torrent_client_root_path": link.get("client_root"),
                                      "local_rel_path": link.get("folder")}.items() if v}
            if disk_ids.get(disk_name) in linked:
                if found is not None and mapping_now.get(disk_ids[disk_name]) != (link.get("client_root"),
                                                                                  link.get("folder")):
                    plan.add(f"~ link client {label} → disk {link['disk']}: path mapping",
                             lambda ref=ref, disk_name=disk_name, body=body: client.post(
                                 f"/api/torrent-clients/{ref()}/disks/{disk_ids[disk_name]}", body))
                continue
            plan.add(f"+ link client {label} → disk {link['disk']}",
                     lambda ref=ref, disk_name=disk_name, body=body: client.post(
                         f"/api/torrent-clients/{ref()}/disks/{disk_ids[disk_name]}", body))
    return ids


def _plan_trackers(plan: Planner, wanted: list[dict], client_ids: dict) -> None:
    client = plan.client
    current = {t["label"].lower(): t for t in client.get("/api/trackers")}
    for spec in wanted or []:
        label = spec["label"]
        found = current.get(label.lower())
        client_name = spec.get("client")
        fields = {"base_url": spec.get("url"), "enabled": spec.get("enabled"), "language": spec.get("language"),
                  "min_seed_time_seconds": duration(spec["min_seed_time"]) if spec.get("min_seed_time") else None,
                  "min_ratio": spec.get("min_ratio"), "seed_rule": spec.get("seed_rule"),
                  "rate_limit_per_min": spec.get("rate_limit")}

        def client_id(name=client_name):
            return client_ids.get(str(name).lower()) if name else None

        if found is None:
            token = _secret_for_create(spec.get("api_token"), f"API token of tracker {label}")
            if not token:
                raise fail(f"Tracker {label}: set its API token ({spec.get('api_token')}) to create it.", EXIT_USAGE)
            announce = env_secret(spec.get("announce_url")) if spec.get("announce_url") else None
            holder: dict = {}

            def create(spec=spec, token=token, announce=announce, fields=fields, holder=holder, client_id=client_id):
                body = {"label": spec["label"], "adapter_type": spec.get("type", "unit3d"), "base_url": spec["url"],
                        "api_token": token, "announce_url": announce, "torrent_client_id": client_id(),
                        **{k: v for k, v in fields.items() if k not in ("base_url", "enabled")}}
                holder.update(client.post("/api/trackers", {k: v for k, v in body.items() if v is not None}))
                if spec.get("enabled") is False:
                    client.patch(f"/api/trackers/{holder['id']}", {"enabled": False})
            plan.add(f"+ tracker {label} ({spec['url']})", create)
            ref: Callable[[], int] = lambda holder=holder: holder["id"]  # noqa: E731
            has_profile = False
        else:
            ref = lambda found=found: found["id"]  # noqa: E731
            has_profile = bool(found.get("upload_profile"))
            changes = _changed(found, fields)
            if client_name and client_ids.get(client_name.lower()) != found.get("torrent_client_id"):
                changes["torrent_client_id"] = None  # risolto all'applicazione (il client può essere nuovo)
            for key in ("api_token", "announce_url"):
                resolved = env_secret(spec.get(key)) if spec.get(key) else None
                if resolved:
                    changes[key] = resolved
            if changes:
                def update(changes=changes, ref=ref, client_id=client_id):
                    body = dict(changes)
                    if "torrent_client_id" in body:
                        body["torrent_client_id"] = client_id()
                    client.patch(f"/api/trackers/{ref()}", body)
                plan.add(f"~ tracker {label}: {', '.join(changes)}", update)
        profile = spec.get("upload_profile")
        if profile:
            _plan_profile(plan, label, profile, ref, has_profile)


def _plan_profile(plan: Planner, label: str, spec: dict, ref: Callable[[], int], exists: bool) -> None:
    client = plan.client
    defaults = spec.get("defaults") or {}
    body = {"default_anonymous": defaults.get("anonymous"),
            "default_personal_release": defaults.get("personal_release"),
            "default_internal": defaults.get("internal"), "default_freeleech": defaults.get("freeleech"),
            "freeleech_options": spec.get("freeleech_options"), "category_id_map": spec.get("category_ids"),
            "type_id_map": spec.get("type_ids"), "resolution_id_map": spec.get("resolution_ids"),
            "naming_rules": spec.get("naming_rules"), "description_template": spec.get("description_template")}
    body = {k: v for k, v in body.items() if v is not None}
    if not exists:
        plan.add(f"+ upload profile {label}" + (f" (preset {spec['preset']})" if spec.get("preset") else ""),
                 lambda ref=ref: client.post(f"/api/trackers/{ref()}/upload-profile",
                                             {"profile_key": spec.get("preset")}))
        if body:
            plan.add(f"~ upload profile {label}: {', '.join(body)}",
                     lambda ref=ref: client.patch(f"/api/trackers/{ref()}/upload-profile", body))
        return
    current = client.get(f"/api/trackers/{ref()}/upload-profile")
    changes = _changed(current, body)
    if "naming_rules" in changes and not current.get("naming_customized") and spec.get("naming_rules") is None:
        changes.pop("naming_rules")
    if changes:
        plan.add(f"~ upload profile {label}: {', '.join(changes)}",
                 lambda ref=ref, changes=changes: client.patch(f"/api/trackers/{ref()}/upload-profile", changes))


def _plan_arr(plan: Planner, wanted: dict) -> None:
    client = plan.client
    for kind in ("radarr", "sonarr"):
        current = {i["label"].lower(): i for i in client.get(f"/api/{kind}-instances")}
        for spec in (wanted or {}).get(kind) or []:
            label = spec["label"]
            found = current.get(label.lower())
            fields = {"base_url": spec.get("url"), "enabled": spec.get("enabled"), "priority": spec.get("priority")}
            if found is None:
                key = _secret_for_create(spec.get("api_key"), f"API key of {kind} {label}")
                if not key:
                    raise fail(f"{kind} {label}: set its API key ({spec.get('api_key')}) to create it.", EXIT_USAGE)
                body = {"label": label, "base_url": spec["url"], "api_key": key,
                        **({"priority": spec["priority"]} if spec.get("priority") is not None else {})}
                plan.add(f"+ {kind} {label} ({spec['url']})",
                         lambda kind=kind, body=body: client.post(f"/api/{kind}-instances", body))
            else:
                changes = _changed(found, fields)
                resolved = env_secret(spec.get("api_key")) if spec.get("api_key") else None
                if resolved:
                    changes["api_key"] = resolved
                if changes:
                    plan.add(f"~ {kind} {label}: {', '.join(changes)}",
                             lambda kind=kind, found=found, changes=changes: client.patch(
                                 f"/api/{kind}-instances/{found['id']}", changes))


def _plan_settings(plan: Planner, wanted: dict, schedule) -> None:
    client = plan.client
    for key, value in (wanted or {}).items():
        value = catalog.normalize(key, str(value).lower() if isinstance(value, bool) else str(value))
        privileged = catalog.needs_login(key, writing=True)
        if not privileged or not any(w in key for w in catalog.SECRET_WORDS):
            current = client.get(f"/api/settings/{key}").get("value")
            if current == value:
                continue
        resolved = env_secret(value)
        if resolved is None:
            continue
        plan.add(f"~ setting {key}" + (" (asks your password)" if privileged else f" = {resolved[:60]}"),
                 lambda key=key, resolved=resolved: (plan.login or client).put(f"/api/settings/{key}",
                                                                              {"value": resolved}),
                 privileged=privileged)
    if schedule is not None:
        cron = None if str(schedule).lower() == "off" else str(schedule)
        current = client.get("/api/schedule")
        if current.get("cron") != cron:
            plan.add(f"~ schedule = {cron or 'off'}", lambda: client.put("/api/schedule", {"cron": cron}))


@app.command("import")
def import_config(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="The YAML file (from nazgarr config export)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would change."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without asking."),
):
    """Apply a configuration file: adds and updates, never removes anything."""
    data = yaml.safe_load(sys.stdin.read() if str(path) == "-" else path.read_text()) or {}
    if data.get("version", VERSION) != VERSION:
        raise fail(f"Unknown file version {data.get('version')}.", EXIT_USAGE)
    plan = Planner(api(ctx))
    disk_ids = _plan_disks(plan, data.get("disks"))
    client_ids = _plan_clients(plan, data.get("torrent_clients"), disk_ids)
    _plan_trackers(plan, data.get("trackers"), client_ids)
    _plan_arr(plan, data.get("arr"))
    _plan_settings(plan, data.get("settings"), data.get("schedule"))
    if not plan.steps:
        console.print("Nothing to change: the instance already matches the file.")
        return
    console.print(f"[bold]{len(plan.steps)} change(s):[/bold]")
    for step in plan.steps:
        console.print(f"  {step.text}")
    if dry_run:
        return
    confirm("Apply them?", yes)
    if any(step.privileged for step in plan.steps):
        err_console.print("Some settings need your password.")
        plan.login = login_api(ctx)
    for step in plan.steps:
        step.apply()
    console.print("[green]Configuration applied.[/green]")
