#!/usr/bin/env python3
"""Hintergrundbilder fuer Reels und Karussells: holen, aufbereiten, sonst Farbfeld.

Vier Stufen, in dieser Reihenfolge:

B  Eigenes Bild. Liegt in der Queue-Datei ein "hintergrund" (Dateiname in
   backgrounds/) oder existiert backgrounds/post-NN[-i].jpg schon, wird das
   genommen. Diese Stufe schlaegt alles - so laesst sich jede Auswahl von Hand
   ueberschreiben.
A1 Ausgesuchtes Bild. Die Queue-Datei nennt unter "bild" die direkte Bild-URL.
   Sie wird beim Redigieren gesetzt, nachdem jemand die Treffer wirklich
   angesehen hat. Der Renderlauf laedt nur noch herunter - kein Schluessel
   noetig, keine Suche, kein Zufall. Das ist der vorgesehene Weg.
A2 Suche im Renderlauf ueber "motiv", braucht PEXELS_API_KEY. Notnagel fuer
   Beitraege, die ohne Redaktion in die Warteschlange kommen; die Auswahl ist
   blind und trifft oft daneben.
C  Prozedurales Farbfeld (nur Reel; Karussells bleiben dann einfarbig). Greift,
   wenn nichts davon liefert - und immer dann, wenn ein Abruf scheitert. Der
   Lauf bricht nie ab, nur weil eine Bilddatenbank gerade nicht antwortet.

"bild" und "hintergrund" duerfen Listen sein, ein Eintrag je Slide. Das ist der
Regelfall: jede Slide zeigt den Ort, von dem ihr Satz handelt. Beim Reel laufen
die Bilder am Wechsel ineinander, beim Karussell ist das Wischen der Wechsel.

Nur Pexels, und nur ueber die Pexels-Lizenz: kommerzielle Nutzung erlaubt,
Namensnennung nicht verlangt. Openverse ist raus, es hat den anonymen Zugang am
31.08.2026 geschlossen (HTTP 401). Der Urheber wird trotzdem in der Queue-Datei
unter "bildnachweis" festgehalten - kostet nichts und ist im Zweifel der Beleg.

Jedes Motivbild wird auf das Markenklima gezogen (blaue Schatten, Kupfer nur in
den Lichtern), weichgezeichnet, abgedunkelt und mit einem Leseschleier hinterlegt.
Ein Foto soll Stimmung tragen, nicht mit der Schrift um Aufmerksamkeit streiten.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageFilter, ImageOps

BG = (27, 35, 54)
FG = (158, 130, 106)

# Dreipunkt-Rampe statt Graustufen: Schatten und Mitten bleiben im Markenblau,
# der Kupferton kommt erst in den Lichtern dazu. Ein reines Duplex zog das ganze
# Bild ins Braune und nahm dem Konto sein Farbklima.
SCHATTEN = np.array((17, 23, 37), np.float32)
MITTEN = np.array((74, 92, 122), np.float32)
LICHTER = np.array((168, 142, 116), np.float32)

ZEITSPERRE = 20  # Sekunden je Abruf; ein haengender Dienst darf den Lauf nicht kippen
ORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backgrounds")


# ----------------------------------------------------------------- Bild besorgen
def _laden(url: str, ziel: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shortheaven3-autoposter/1.0"})
        with urllib.request.urlopen(req, timeout=ZEITSPERRE) as r:
            roh = r.read(25 * 1024 * 1024)
        if len(roh) < 20_000:
            return False
        # Erst in eine Nebendatei schreiben und pruefen, dann umbenennen. Sonst
        # zerstoert ein halber oder kaputter Download ein vorhandenes Bild.
        teil = ziel + ".teil"
        with open(teil, "wb") as f:
            f.write(roh)
        Image.open(teil).verify()
        os.replace(teil, ziel)
        return True
    except Exception as e:
        print(f"  Bild nicht geladen ({type(e).__name__}: {e})")
        if os.path.exists(ziel + ".teil"):
            os.remove(ziel + ".teil")
        return False


def _pexels(motiv: str, ziel: str) -> bool:
    """Pexels, falls ein Schluessel hinterlegt ist. Kostenloser Zugang, kein Abo."""
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return False
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": motiv, "orientation": "portrait", "size": "large", "per_page": 12})
    try:
        req = urllib.request.Request(url, headers={"Authorization": key,
                                                   "User-Agent": "shortheaven3-autoposter/1.0"})
        with urllib.request.urlopen(req, timeout=ZEITSPERRE) as r:
            treffer = json.load(r).get("photos", [])
    except Exception as e:
        print(f"  Pexels nicht erreichbar ({type(e).__name__}: {e})")
        return False
    print(f"  Pexels: {len(treffer)} Treffer")
    for t in treffer:
        quelle = (t.get("src") or {}).get("large2x") or (t.get("src") or {}).get("large")
        if quelle and _laden(quelle, ziel):
            print(f"  genommen: {t.get('alt') or motiv} ({t.get('url')})")
            return True
    return False


def von_url(url: str, ziel: str) -> bool:
    """Weg A1: ein beim Redigieren ausgesuchtes Bild holen. Kein Schluessel noetig."""
    print(f"  ausgesuchtes Bild: {url}")
    return _laden(url, ziel)


def besorgen(motiv: str, ziel: str) -> bool:
    """Weg A2: blind suchen. Nur Notnagel - normalerweise steht "bild" in der Datei."""
    for begriff in [b.strip() for b in motiv.split("|") if b.strip()]:
        print(f"  Motiv gesucht: {begriff!r}")
        if _pexels(begriff, ziel):
            return True
    return False


# -------------------------------------------------------------- Bild aufbereiten
def _vignette(bw: int, bh: int) -> np.ndarray:
    vw, vh = bw // 8, bh // 8
    yy, xx = np.mgrid[0:vh, 0:vw].astype(np.float32)
    d = np.sqrt(((xx - vw / 2) / (vw / 2)) ** 2 + ((yy - vh / 2) / (vh / 2)) ** 2)
    v = np.clip(1.18 - 0.48 * d, 0.44, 1.0)
    return np.asarray(Image.fromarray((v * 255).astype(np.uint8)).resize(
        (bw, bh), Image.BICUBIC)).astype(np.float32) / 255.0


def _leseschleier(bw: int, bh: int, mitte: float) -> np.ndarray:
    """Dunkler Verlauf um die Textmitte. Ohne ihn frisst ein helles Foto die Schrift."""
    y = np.linspace(0, 1, bh, dtype=np.float32)
    d = np.abs(y - mitte) / 0.27
    return np.clip(1.0 - 0.44 * np.clip(1.0 - d, 0, 1) ** 1.4, 0, 1)[:, None, None]


def aufbereiten(pfad: str, bw: int, bh: int, mitte: float = 0.45) -> np.ndarray:
    """Foto -> Markenklima. Liefert ein Feld der Groesse (bh, bw, 3) als uint8."""
    im = ImageOps.exif_transpose(Image.open(pfad)).convert("RGB")

    # Auf das Zielformat beschneiden, dann auf die Zuggroesse bringen.
    ziel = bw / bh
    w, h = im.size
    if w / h > ziel:
        neu = int(h * ziel)
        im = im.crop(((w - neu) // 2, 0, (w - neu) // 2 + neu, h))
    else:
        neu = int(w / ziel)
        oben = int((h - neu) * 0.38)  # etwas ueber der Mitte, das traegt bei Innenraeumen besser
        im = im.crop((0, oben, w, oben + neu))
    im = im.resize((bw, bh), Image.LANCZOS).filter(ImageFilter.GaussianBlur(4))

    # Duplex: Helligkeit des Fotos zwischen Markenblau und gedaempftem Kupfer abbilden.
    l = np.asarray(im.convert("L")).astype(np.float32) / 255.0
    l = np.clip((l - 0.46) * 1.06 + 0.46, 0, 1)         # Kontrast fast erhalten
    l = (0.07 + 0.93 * l)[..., None]                    # Schatten leicht anheben
    a = SCHATTEN + (MITTEN - SCHATTEN) * l              # blaues Grundklima
    a += (LICHTER - a) * (l ** 2.4) * 0.92              # Kupfer nur in den Lichtern

    a *= _vignette(bw, bh)[..., None]
    a *= _leseschleier(bw, bh, mitte)
    return np.clip(a, 0, 255).astype(np.uint8)


# ------------------------------------------------------------ Prozedurales Feld
def feld(seed: int, bw: int, bh: int) -> np.ndarray:
    """Weg C: atmosphaerisches Farbfeld, sichtbarer als frueher.

    Frueher lag alles dicht am Hintergrundton und war im fertigen Reel kaum zu
    erkennen. Jetzt kommen ein schraeger Lichtschacht und deutlichere Ballungen
    dazu, damit auch ohne Foto etwas zu sehen ist.
    """
    rng = np.random.default_rng(seed)
    sw, sh = bw // 4, bh // 4
    a = np.zeros((sh, sw, 3), np.float32) + np.array(BG, np.float32)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)

    for _ in range(6):
        cx, cy = rng.uniform(0.08, 0.92) * sw, rng.uniform(0.08, 0.92) * sh
        r = rng.uniform(0.30, 0.72) * sw
        warm = rng.uniform(0, 1) < 0.5
        col = np.array(FG if warm else (52, 70, 104), np.float32)
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        m = np.clip(1.0 - d, 0, 1) ** 1.9 * (0.42 if warm else 0.72)
        a += m[..., None] * (col - a) * 0.9

    # Lichtschacht: eine schraege Bahn, wie Licht durch ein Fenster.
    winkel = rng.uniform(-0.55, 0.55)
    pos = rng.uniform(0.25, 0.75) * sw
    breite = rng.uniform(0.16, 0.30) * sw
    bahn = np.clip(1.0 - np.abs((xx + winkel * yy) - pos) / breite, 0, 1) ** 1.7
    bahn *= np.clip(1.0 - yy / sh * 0.65, 0, 1)
    a += bahn[..., None] * (np.array(FG, np.float32) - a) * 0.40

    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(13))
    a = np.asarray(im.resize((bw, bh), Image.BICUBIC)).astype(np.float32)
    a *= _vignette(bw, bh)[..., None]
    return np.clip(a, 0, 255).astype(np.uint8)


# ------------------------------------------------------- Welches Bild je Slide
def je_slide(wert, si: int):
    """Ein Feld kann fuer alle Slides gelten oder je Slide einen Eintrag haben."""
    if isinstance(wert, list):
        return wert[si] if si < len(wert) else (wert[-1] if wert else None)
    return wert


def bildpfad(spec: dict, si: int) -> str | None:
    """Hintergrundbild fuer Slide si, bei Bedarf geholt. None heisst: kein Bild.

    Gilt fuer Reel und Karussell gleichermassen. "bild" und "hintergrund" duerfen
    Listen sein - dann bekommt jede Slide ihr eigenes Motiv, passend zu dem Satz,
    der gerade steht.
    """
    nr = spec["post"]
    mehrere = isinstance(spec.get("bild"), list) or isinstance(spec.get("hintergrund"), list)
    marke = f"post-{nr}-{si + 1}" if mehrere else f"post-{nr}"

    eigen = je_slide(spec.get("hintergrund"), si)
    if eigen:
        pfad = eigen if os.path.isabs(eigen) else os.path.join(ORDNER, eigen)
        if os.path.exists(pfad):
            return pfad
        print(f"  hintergrund {eigen!r} fehlt - weiter mit Motiv oder ohne Bild")

    pfad = os.path.join(ORDNER, f"{marke}.jpg")
    merk = os.path.join(ORDNER, f"{marke}.quelle")
    bild = je_slide(spec.get("bild"), si)
    motiv = je_slide(spec.get("motiv"), si)

    vorhanden = os.path.exists(pfad)
    if vorhanden:
        # Liegt schon ein Bild da, wird es behalten - sonst holte jeder Lauf neu.
        # Ausnahme: In der Queue-Datei steht inzwischen eine andere URL. Ohne
        # diese Pruefung bliebe eine korrigierte Auswahl folgenlos, weil die alte
        # Datei den Vorrang behaelt.
        alt = ""
        if os.path.exists(merk):
            with open(merk, encoding="utf-8") as f:
                alt = f.read().strip()
        if not bild or alt == bild:
            return pfad
        print("  Bildquelle hat sich geaendert - wird neu geholt")

    if not bild and not motiv:
        return None
    os.makedirs(ORDNER, exist_ok=True)
    if (bild and von_url(bild, pfad)) or (motiv and besorgen(motiv, pfad)):
        with open(merk, "w", encoding="utf-8") as f:
            f.write((bild or f"suche: {motiv}") + "\n")
        return pfad
    if vorhanden:
        print("  Neuholen gescheitert - das alte Bild bleibt stehen")
        return pfad
    print("  kein Motivbild bekommen")
    return None


def bildpfade(spec: dict) -> list[str | None]:
    """Ein Pfad je Slide, None wo es kein Bild gibt."""
    return [bildpfad(spec, si) for si in range(len(spec["slides"]))]
