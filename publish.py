#!/usr/bin/env python3
"""
Autoposter für @shortheaven3.

Liest schedule.json, sucht den ersten fälligen, noch nicht veröffentlichten
Beitrag und veröffentlicht ihn über die Instagram Graph API.

Schutzmechanismen:
  * Genau EIN Beitrag pro Lauf, auch wenn mehrere überfällig sind.
  * Idempotenz über published_id: veröffentlichte Beiträge werden übersprungen.
  * Live-Duplikatsprüfung gegen den tatsächlichen Instagram-Feed unmittelbar vor
    jeder Veröffentlichung: schützt auch dann, wenn ein zweiter, parallel
    laufender Prozess (z. B. ein manueller/geplanter Lauf) noch eine veraltete
    Kopie von schedule.json sieht, in der der Beitrag als unveröffentlicht
    gilt. Die Prüfung erfolgt gegen die Wahrheit (Instagram selbst), nicht
    gegen schedule.json.
  * Kontingentprüfung vor jeder Veröffentlichung.
  * Trockenlauf über --dry-run oder DRY_RUN=1.

Aufruf:
    python publish.py            # echter Lauf
    python publish.py --dry-run  # nichts wird veröffentlicht
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

GRAPH_VERSION = "v21.0"
GRAPH_HOST = "https://graph.instagram.com"

REPO_ROOT = Path(__file__).resolve().parent
SCHEDULE_PATH = REPO_ROOT / "schedule.json"
IMAGE_DIR = REPO_ROOT / "images"

# Basis-URL für die Bilder im Repository. Wird aus den GitHub-Actions-Variablen
# gebaut, lässt sich aber über IMAGE_BASE_URL überschreiben.
DEFAULT_IMAGE_BASE = "https://raw.githubusercontent.com/{repo}/{branch}/images"


class PublishError(RuntimeError):
    """Fehler, der den Lauf mit Exit-Code 1 beendet."""


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _request(method: str, url: str, params: dict | None = None) -> dict:
    params = params or {}
    data = None
    if method == "POST":
        data = urllib.parse.urlencode(params).encode()
    else:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise PublishError(f"{method} {url.split('?')[0]} -> HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise PublishError(f"Netzwerkfehler bei {method} {url.split('?')[0]}: {exc.reason}") from exc


def graph_get(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    return _request("GET", f"{GRAPH_HOST}/{GRAPH_VERSION}/{path}", params)


def graph_post(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    return _request("POST", f"{GRAPH_HOST}/{GRAPH_VERSION}/{path}", params)


# --------------------------------------------------------------------------
# Instagram
# --------------------------------------------------------------------------

def check_quota(ig_user_id: str, token: str) -> None:
    """Bricht ab, wenn das 24-Stunden-Kontingent erschöpft ist."""
    result = graph_get(f"{ig_user_id}/content_publishing_limit", token,
                       fields="config,quota_usage")
    entry = (result.get("data") or [{}])[0]
    usage = entry.get("quota_usage", 0)
    total = (entry.get("config") or {}).get("quota_total", 100)
    print(f"[quota] {usage} von {total} Beiträge in den letzten 24 h verbraucht")
    if usage >= total:
        raise PublishError("Kontingent erschöpft — Lauf wird abgebrochen.")


def wait_for_container(container_id: str, token: str, timeout: int = 120) -> None:
    """Wartet, bis der Container den Status FINISHED erreicht."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = graph_get(container_id, token, fields="status_code,status").get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            detail = graph_get(container_id, token, fields="status").get("status", "")
            raise PublishError(f"Container {container_id} fehlgeschlagen: {detail}")
        print(f"[container] Status {status} — warte …")
        time.sleep(5)
    raise PublishError(f"Container {container_id} wurde nicht rechtzeitig fertig.")


def create_image_container(ig_user_id: str, token: str, image_url: str,
                           caption: str, is_carousel_item: bool = False) -> str:
    params = {"image_url": image_url}
    if is_carousel_item:
        params["is_carousel_item"] = "true"
    else:
        params["caption"] = caption
    result = graph_post(f"{ig_user_id}/media", token, **params)
    container_id = result.get("id")
    if not container_id:
        raise PublishError(f"Keine Container-ID erhalten: {result}")
    return container_id


def create_carousel_container(ig_user_id: str, token: str,
                              children: list[str], caption: str) -> str:
    result = graph_post(f"{ig_user_id}/media", token,
                        media_type="CAROUSEL",
                        children=",".join(children),
                        caption=caption)
    container_id = result.get("id")
    if not container_id:
        raise PublishError(f"Keine Sammelcontainer-ID erhalten: {result}")
    return container_id


def publish_container(ig_user_id: str, token: str, container_id: str) -> str:
    result = graph_post(f"{ig_user_id}/media_publish", token, creation_id=container_id)
    media_id = result.get("id")
    if not media_id:
        raise PublishError(f"Veröffentlichung lieferte keine Media-ID: {result}")
    return media_id


def get_permalink(media_id: str, token: str) -> str:
    try:
        return graph_get(media_id, token, fields="permalink").get("permalink", "")
    except PublishError:
        return ""


def normalize_caption(text: str) -> str:
    """Normalisiert eine Caption für den Vergleich (Whitespace/Zeilenumbrüche egal)."""
    return " ".join((text or "").split())


def find_recent_duplicate(ig_user_id: str, token: str, caption: str,
                          limit: int = 30) -> dict | None:
    """Prüft die zuletzt veröffentlichten Beiträge auf eine (nahezu) identische Caption.

    Das ist die eigentliche Absicherung gegen Doppel-Veröffentlichung: Ob ein
    zweiter, gleichzeitig laufender Prozess (z. B. ein manueller Lauf mit einer
    veralteten schedule.json-Kopie, etwa über einen gecachten
    raw.githubusercontent.com-Abruf) denselben Beitrag noch einmal einreichen
    will, spielt keine Rolle — hier wird gegen den tatsächlichen Instagram-Feed
    geprüft, nicht gegen schedule.json. Läuft absichtlich VOR jedem
    Container-Aufruf, damit im Duplikatsfall gar nichts unwiderruflich passiert.
    """
    target = normalize_caption(caption)
    if not target:
        return None
    result = graph_get(f"{ig_user_id}/media", token,
                       fields="id,caption,timestamp,permalink", limit=limit)
    for item in result.get("data", []):
        if normalize_caption(item.get("caption", "")) == target:
            return item
    return None


# --------------------------------------------------------------------------
# Redaktionsplan
# --------------------------------------------------------------------------

def load_schedule() -> dict:
    if not SCHEDULE_PATH.exists():
        raise PublishError(f"{SCHEDULE_PATH.name} nicht gefunden.")
    return json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))


def save_schedule(schedule: dict) -> None:
    SCHEDULE_PATH.write_text(
        json.dumps(schedule, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def pick_due_post(schedule: dict, today: date) -> dict | None:
    """ÄLtester fälliger Beitrag ohne published_id. Genau einer pro Lauf."""
    due = [
        p for p in schedule.get("posts", [])
        if not p.get("published_id")
        and date.fromisoformat(p["date"]) <= today
    ]
    if not due:
        return None
    due.sort(key=lambda p: p["date"])
    if len(due) > 1:
        nummern = ", ".join(str(p.get("post")) for p in due[1:])
        print(f"[plan] {len(due)} Beiträge überfällig — heute nur der älteste. "
              f"Zurückgestellt: {nummern}")
    return due[0]


def image_url_for(filename: str) -> str:
    base = os.environ.get("IMAGE_BASE_URL")
    if not base:
        repo = os.environ.get("GITHUB_REPOSITORY")
        branch = os.environ.get("GITHUB_REF_NAME", "main")
        if not repo:
            raise PublishError(
                "Weder IMAGE_BASE_URL noch GITHUB_REPOSITORY gesetzt — "
                "die Bild-URL lässt sich nicht bilden."
            )
        base = DEFAULT_IMAGE_BASE.format(repo=repo, branch=branch)
    return f"{base.rstrip('/')}/{filename}"


def verify_local_images(post: dict) -> None:
    names = post.get("images") or [post.get("image")]
    missing = [n for n in names if n and not (IMAGE_DIR / n).exists()]
    if missing:
        raise PublishError(
            f"Bilddatei(en) fehlen im Ordner images/: {', '.join(missing)}"
        )


# --------------------------------------------------------------------------
# Hauptlauf
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Instagram-Autoposter")
    parser.add_argument("--dry-run", action="store_true",
                        help="Nichts veröffentlichen, nur zeigen, was passieren würde.")
    args = parser.parse_args()

    dry_run = args.dry_run or os.environ.get("DRY_RUN") == "1"

    ig_user_id = os.environ.get("IG_USER_ID", "").strip()
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not dry_run and (not ig_user_id or not token):
        raise PublishError("IG_USER_ID und IG_ACCESS_TOKEN müssen gesetzt sein.")
    if dry_run:
        fehlend = [n for n, v in (("IG_USER_ID", ig_user_id),
                                ("IG_ACCESS_TOKEN", token)) if not v]
        if fehlend:
            print(f"[dry-run] Hinweis: {', '.join(fehlend)} noch nicht gesetzt. "
                  f"Fuer den echten Lauf noetig, fuer den Trockenlauf nicht.")

    today = datetime.now(timezone.utc).date()
    schedule = load_schedule()
    post = pick_due_post(schedule, today)

    if post is None:
        print(f"[plan] Für {today.isoformat()} ist nichts fällig. Nichts zu tun.")
        return 0

    nummer = post.get("post")
    is_carousel = bool(post.get("images"))
    print(f"[plan] Fällig: Beitrag {nummer} vom {post['date']} "
          f"({'Karussell' if is_carousel else 'Einzelbild'})")

    verify_local_images(post)

    if dry_run:
        urls = [image_url_for(n) for n in (post.get("images") or [post["image"]])]
        print("[dry-run] Es würde veröffentlicht:")
        print(f"[dry-run]   Beitrag : {nummer} — {post.get('saeule', '')}")
        for u in urls:
            print(f"[dry-run]   Bild    : {u}")
        print(f"[dry-run]   Caption : {post['caption'][:120]}…")
        print("[dry-run] Keine Veröffentlichung durchgeführt.")
        return 0

    check_quota(ig_user_id, token)

    duplicate = find_recent_duplicate(ig_user_id, token, post["caption"])
    if duplicate:
        print(f"[schutz] Beitrag {nummer} scheint bereits veröffentlicht zu sein "
              f"(Media-ID {duplicate.get('id')}, {duplicate.get('timestamp', '')}) "
              f"— ein anderer Lauf war schneller. Trage vorhandene ID nach, "
              f"veröffentliche NICHT erneut.")
        post["published_id"] = duplicate.get("id")
        post["published_at"] = duplicate.get("timestamp") or datetime.now(timezone.utc).isoformat()
        if duplicate.get("permalink"):
            post["permalink"] = duplicate["permalink"]
        save_schedule(schedule)
        print(f"[fertig] Beitrag {nummer} als bereits veröffentlicht markiert — "
              f"keine neue Veröffentlichung ausgelöst.")
        return 0

    if is_carousel:
        children = []
        for name in post["images"]:
            cid = create_image_container(ig_user_id, token, image_url_for(name),
                                        caption="", is_carousel_item=True)
            wait_for_container(cid, token)
            children.append(cid)
            print(f"[container] Kind-Container {cid} für {name}")
        container_id = create_carousel_container(ig_user_id, token, children,
                                                post["caption"])
    else:
        container_id = create_image_container(ig_user_id, token,
                                              image_url_for(post["image"]),
                                            post["caption"])

    print(f"[container] Sammelcontainer {container_id}")
    wait_for_container(container_id, token)

    media_id = publish_container(ig_user_id, token, container_id)
    permalink = get_permalink(media_id, token)

    post["published_id"] = media_id
    post["published_at"] = datetime.now(timezone.utc).isoformat()
    if permalink:
        post["permalink"] = permalink
    save_schedule(schedule)

    print(f"[fertig] Beitrag {nummer} veröffentlicht — Media-ID {media_id}")
    if permalink:
        print(f"[fertig] {permalink}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PublishError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        sys.exit(1)
