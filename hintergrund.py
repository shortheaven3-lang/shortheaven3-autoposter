#!/usr/bin/env python3
"""Hintergruende fuer Reels: Motivbild holen, aufbereiten, sonst Farbfeld.

Drei Wege, in dieser Reihenfolge:

A  Motivbild aus einer freien Bilddatenbank. Die Queue-Datei nennt unter "motiv"
   einen englischen Suchbegriff; mehrere durch "|" getrennte Begriffe werden der
   Reihe nach probiert. Gesucht wird nur nach Bildern, die ohne
   Namensnennung kommerziell nutzbar sind (Pexels-Lizenz bzw. CC0/Public Domain).
   Das gefundene Bild wird nach backgrounds/post-NN.jpg gelegt und mitcommittet -
   ein zweiter Lauf holt nichts neu, das Reel bleibt reproduzierbar.
B  Eigenes Bild. Liegt in der Queue-Datei ein "hintergrund" (Dateiname in
   backgrounds/) oder existiert backgrounds/post-NN.jpg schon, wird das genommen.
   Damit laesst sich jedes automatisch geholte Bild von Hand ersetzen.
C  Prozedurales Farbfeld wie bisher. Greift, wenn A und B nichts liefern - und
   immer dann, wenn der Abruf im Renderlauf scheitert. Der Lauf bricht nie ab,
   nur weil eine Bilddatenbank gerade nicht antwortet.

Zur Bildqualitaet: Openverse braucht keinen Schluessel, sein CC0-Bestand ist aber
duenn und ungleich - fuer viele Alltagsmotive kommt nichts zurueck. Ein kostenlos
erhaeltlicher Pexels-Schluessel (Repo-Secret PEXELS_API_KEY, kein Abo) hebt die
Trefferquote und die Anmutung deutlich; ohne ihn bleibt es oft beim Farbfeld.

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


# ----------------------------------------------------------------- Bild besorgen
def _laden(url: str, ziel: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shortheaven3-autoposter/1.0"})
        with urllib.request.urlopen(req, timeout=ZEITSPERRE) as r:
            roh = r.read(25 * 1024 * 1024)
        if len(roh) < 20_000:
            return False
        with open(ziel, "wb") as f:
            f.write(roh)
        Image.open(ziel).verify()
        return True
    except Exception as e:
        print(f"  Bild nicht geladen ({type(e).__name__}: {e})")
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


def _openverse(motiv: str, ziel: str) -> bool:
    """Openverse ohne Schluessel. Nur CC0 und Public Domain - keine Namensnennung noetig."""
    # Kein Seitenverhaeltnis-Filter: der CC0-Bestand ist klein, und beschnitten
    # wird ohnehin. Nur die Aufloesung muss reichen.
    url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": motiv, "license": "cc0,pdm", "page_size": 40, "mature": "false"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shortheaven3-autoposter/1.0"})
        with urllib.request.urlopen(req, timeout=ZEITSPERRE) as r:
            antwort = json.load(r)
    except Exception as e:
        print(f"  Openverse nicht erreichbar ({type(e).__name__}: {e})")
        return False
    treffer = antwort.get("results", [])
    print(f"  Openverse: {antwort.get('result_count', 0)} Treffer, {len(treffer)} geliefert")
    for t in treffer:
        if (t.get("height") or 0) < 700 or (t.get("width") or 0) < 700:
            continue
        quelle = t.get("url")
        if quelle and _laden(quelle, ziel):
            print(f"  genommen: {t.get('title')} [{t.get('license')}] {t.get('foreign_landing_url')}")
            return True
    return False


def besorgen(motiv: str, ziel: str) -> bool:
    """Holt ein Motivbild nach ziel.

    Pexels schlaegt Openverse, wenn ein Schluessel hinterlegt ist. Mehrere mit "|"
    getrennte Begriffe werden nacheinander probiert - der CC0-Bestand ist duenn,
    ein zweiter Begriff rettet oft den Beitrag.
    """
    for begriff in [b.strip() for b in motiv.split("|") if b.strip()]:
        print(f"  Motiv gesucht: {begriff!r}")
        if _pexels(begriff, ziel) or _openverse(begriff, ziel):
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
