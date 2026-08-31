#!/usr/bin/env python3
"""Rendert einen Beitrag als Reel: 1080x1920, EB Garamond, eigener Ton.

Wird von render.py aufgerufen, laesst sich aber auch einzeln nutzen:
    python3 render_reel.py queue/post-33.json videos/post-33.mp4
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import musik
import hintergrund
import stimme

W, H, CX, FPS = 1080, 1920, 540, 24
BG = (27, 35, 54)
FG = (158, 130, 106)

# Reels-Sicherheitszone: oben rund 140 px Profilzeile, unten rund 330 px
# Caption und Schaltflaechen. Nutzbar bleibt 140-1590, Mitte bei 865.
SAFE_MID = 865
SAFE_FUSS = 1468

BASE = os.path.dirname(os.path.abspath(__file__))
SUCHORTE = (os.path.join(BASE, "fonts"), "/usr/share/fonts",
            "/usr/local/share/fonts", os.path.expanduser("~/.fonts"))


def font_pfad(*muster):
    for m in muster:
        for ort in SUCHORTE:
            for endung in (".otf", ".ttf"):
                treffer = sorted(glob.glob(os.path.join(ort, "**", m + endung),
                                           recursive=True))
                if treffer:
                    return treffer[0]
    raise SystemExit("EB Garamond nicht gefunden (apt-get install fonts-ebgaramond)")


ITALIC = font_pfad("EBGaramond12-Italic", "EBGaramond08-Italic", "EBGaramond*Italic")
REGULAR = font_pfad("EBGaramond12-Regular", "EBGaramond08-Regular", "EBGaramond*Regular")


# ----------------------------------------------------------------- Hintergrund
# Der Hintergrund kommt aus hintergrund.py. Reihenfolge: eigene Datei in
# backgrounds/, sonst die beim Redigieren ausgesuchte Bild-URL aus dem Feld
# "bild", sonst eine blinde Suche ueber "motiv", sonst das prozedurale Farbfeld.
# Ein geholtes Bild bleibt als Datei liegen und wird mitcommittet - der naechste
# Lauf holt nichts neu, das Reel bleibt Bild fuer Bild reproduzierbar.
ZUG_W, ZUG_H = int(W * 1.25), int(H * 1.25)  # groesser als das Bild, fuer den langsamen Zug


def hintergruende(spec: dict) -> list[np.ndarray]:
    """Ein Feld je Slide. Gleiche Datei wird nur einmal aufbereitet."""
    felder, lager = [], {}
    for si, pfad in enumerate(hintergrund.bildpfade(spec)):
        if pfad and pfad not in lager:
            try:
                lager[pfad] = hintergrund.aufbereiten(pfad, ZUG_W, ZUG_H,
                                                      mitte=SAFE_MID / H)
                print(f"  Slide {si + 1}: {os.path.relpath(pfad, BASE)}")
            except Exception as e:
                print(f"  {pfad} unbrauchbar ({type(e).__name__}: {e}) - Farbfeld")
                lager[pfad] = None
        fertig = lager.get(pfad) if pfad else None
        felder.append(fertig if fertig is not None
                      else hintergrund.feld(spec["post"] * 100 + si, ZUG_W, ZUG_H))
    return felder


# ------------------------------------------------------------------ Textebenen
def wrap(d, text, fnt, max_w):
    out, cur = [], ""
    for w in text.split():
        probe = (cur + " " + w).strip()
        if d.textlength(probe, font=fnt) <= max_w or not cur:
            cur = probe
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def tracked(d, text, fnt, y, tracking):
    ws = [d.textlength(c, font=fnt) for c in text]
    x = CX - (sum(ws) + tracking * (len(text) - 1)) / 2
    for c, w in zip(text, ws):
        d.text((x, y), c, font=fnt, fill=FG + (255,), anchor="la")
        x += w + tracking


# Titelbild je Saeule: Schriftgroesse und Hoehe im Bild unterscheiden sich,
# damit sich die Beitraege im Profilraster nicht gleichen. Der erste Frame des
# Reels ist das Vorschaubild - er entscheidet, ob jemand haengen bleibt.
HOOK_VARIANTEN = {
    "Der Spiegel": {"groesse": 88, "mitte": 865, "linie_oben": False},
    "Das Ritual": {"groesse": 80, "mitte": 770, "linie_oben": True},
    "Die Frage": {"groesse": 104, "mitte": 855, "linie_oben": False},
    "Die Stille": {"groesse": 72, "mitte": 975, "linie_oben": False},
}


def ebene(slide: dict, saeule: str = "") -> np.ndarray:
    """Fertige RGBA-Ebene, Satzspiegel um SAFE_MID zentriert."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    typ = slide.get("typ", "inhalt")
    gross = typ == "hook"
    v = HOOK_VARIANTEN.get(saeule, HOOK_VARIANTEN["Der Spiegel"])

    f_head = ImageFont.truetype(ITALIC, v["groesse"] if gross else 76)
    lead_h = (v["groesse"] + 12) if gross else 88
    kopf = wrap(d, slide["headline"], f_head, 900)

    rumpf_text = slide.get("unterzeile") if gross else slide.get("text", "")
    f_txt = ImageFont.truetype(ITALIC, 52 if gross else 48)
    lead_t = 66 if gross else 60
    rumpf = wrap(d, rumpf_text, f_txt, 840) if rumpf_text else []

    linie = typ != "hook"
    hoehe = len(kopf) * lead_h + (58 if linie else 40 if rumpf else 0) + len(rumpf) * lead_t
    y = (v["mitte"] if gross else SAFE_MID) - hoehe // 2
    if gross and v["linie_oben"]:
        d.rectangle([492, y - 96, 587, y - 95], fill=FG + (185,))

    if slide.get("ziffer"):
        tracked(d, slide["ziffer"], ImageFont.truetype(REGULAR, 20), y - 118, 6)

    for i, l in enumerate(kopf):
        d.text((CX, y + i * lead_h), l, font=f_head, fill=FG + (255,), anchor="ma")
    y += len(kopf) * lead_h

    if linie:
        y += 26
        d.rectangle([492, y, 587, y + 1], fill=FG + (185,))
        y += 32
    elif rumpf:
        y += 40

    for i, l in enumerate(rumpf):
        d.text((CX, y + i * lead_t), l, font=f_txt, fill=FG + (220,), anchor="ma")

    if typ == "cta":
        tracked(d, "@SHORTHEAVEN3", ImageFont.truetype(REGULAR, 24), SAFE_FUSS, 4)
    return np.asarray(img).astype(np.float32)


# ------------------------------------------------------------------------ Film
VORLAUF, NACHLAUF = 0.7, 1.5   # Stille vor und nach dem gesprochenen Satz
UEBERBLENDUNG = 0.9            # Sekunden, in denen zwei Hintergruende ineinander laufen


def zeiten(slides: list, mindest: list[float] | None = None) -> list[float]:
    """Standzeit nach Lesemenge - und, wenn gesprochen wird, nach der Sprechdauer.

    Vorher stand jeder Satz gleich lang, egal wie viel darauf zu lesen war. Jetzt
    bekommt jede Slide 2,5 s Grundzeit plus 0,4 s je Wort, mindestens 6 s. Wird
    vorgelesen, ist die Sprechdauer plus Vor- und Nachlauf die harte Untergrenze:
    ein Satz darf nie abgeschnitten werden, auch nicht von der Deckelung.
    """
    GRUND, JE_WORT, MIN, MAX, GESAMT_MAX = 2.5, 0.4, 6.0, 10.5, 44.0
    mindest = mindest or [0.0] * len(slides)
    boden, dauer = [], []
    for s, m in zip(slides, mindest):
        rumpf = s.get("unterzeile") if s.get("typ") == "hook" else s.get("text", "")
        woerter = len((s.get("headline", "") + " " + (rumpf or "")).split())
        b = max(MIN, m)
        boden.append(b)
        dauer.append(max(b, min(MAX, GRUND + JE_WORT * woerter)))
    gesamt, bodensumme = sum(dauer), sum(boden)
    if gesamt > GESAMT_MAX and bodensumme < GESAMT_MAX:
        # Nur der Anteil ueber den Untergrenzen wird gekuerzt.
        f = (GESAMT_MAX - bodensumme) / (gesamt - bodensumme)
        dauer = [b + (d - b) * f for d, b in zip(dauer, boden)]
    return [round(d, 2) for d in dauer]


def ease(t):
    return t * t * (3 - 2 * t)


def bauen(spec: dict, ziel: str) -> str:
    slides = spec["slides"]
    nr = spec["post"]

    # Die Stimme kommt vor der Zeitrechnung: wie lange eine Slide steht, haengt
    # davon ab, wie lange ihr Satz gesprochen dauert.
    clips = None
    if spec.get("stimme", True):
        clips = stimme.aufnehmen([stimme.satz_fuer(s) for s in slides],
                                 os.path.join(BASE, "stimmen"))
        if clips is None:
            print("  ohne Stimme - nur Musik")
    sprech = [c.shape[0] / stimme.SR for c in clips] if clips else None
    dauer = zeiten(slides, [VORLAUF + d + NACHLAUF for d in sprech] if sprech else None)
    gesamt = sum(dauer)

    os.makedirs(os.path.dirname(os.path.abspath(ziel)) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        ton = musik.spur(os.path.join(tmp, "ton.wav"), gesamt,
                         spec.get("saeule", ""), seed=nr,
                         anbieter=os.environ.get("MUSIK_ANBIETER", "eigen"))
        if clips:
            starts, t0 = [], 0.0
            for d in dauer:
                starts.append(t0 + VORLAUF)
                t0 += d
            ton = stimme.mischen(stimme.wav_lesen(ton), clips, starts,
                                 os.path.join(tmp, "misch.wav"))
            print(f"  Stimme: {len(clips)} Saetze, {sum(sprech):.1f} s gesprochen")

        felder = hintergruende(spec)
        ebenen = [ebene(s, spec.get("saeule", "")) for s in slides]
        rng = np.random.default_rng(7)
        korn = [rng.normal(0, 2.6, (H, W, 1)).astype(np.float32) for _ in range(10)]

        p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
             "-i", "-", "-i", ton,
             "-c:v", "libx264", "-preset", "medium", "-crf", "23",
             "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
             "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
             "-shortest", "-movflags", "+faststart", ziel],
            stdin=subprocess.PIPE)

        k, letztes = 0, None
        for si, (sl, dur) in enumerate(zip(slides, dauer)):
            n = int(dur * FPS)
            bg, tx = felder[si], ebenen[si]
            BH, BW = bg.shape[:2]
            # Nur ueberblenden, wenn die Slide wirklich ein anderes Bild bekommt.
            # Bei einem Bild fuer den ganzen Beitrag traegt der langsame Zug allein,
            # eine Blende darueber saehe aus wie ein Ruecksprung.
            blende = si > 0 and felder[si] is not felder[si - 1]
            for f in range(n):
                t = f / n
                z = 1.0 - 0.055 * t
                cw, ch = int(W * z * 1.25), int(H * z * 1.25)
                ox = int((BW - cw) * (0.5 + 0.10 * (t - 0.5)))
                oy = int((BH - ch) * (0.5 - 0.14 * (t - 0.5)))
                grund = np.asarray(
                    Image.fromarray(bg[oy:oy + ch, ox:ox + cw]).resize(
                        (W, H), Image.BILINEAR)).astype(np.float32)
                if blende and letztes is not None and t * dur < UEBERBLENDUNG:
                    m = ease(min(1.0, t * dur / UEBERBLENDUNG))
                    grund = letztes * (1 - m) + grund * m
                frame = grund
                tin, tout = 0.75 / dur, 0.55 / dur
                a = (ease(min(1.0, t / tin)) if t < tin
                     else ease(max(0.0, (1 - t) / tout)) if t > 1 - tout else 1.0)
                if a > 0.003:
                    rise = int(26 * (1 - a))
                    lay = np.roll(tx, rise, axis=0) if rise else tx
                    al = (lay[..., 3:4] / 255.0) * a
                    frame = grund * (1 - al) + lay[..., :3] * al
                frame = frame + korn[k % 10]
                k += 1
                p.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
            letztes = grund
        p.stdin.close()
        if p.wait() != 0:
            raise SystemExit("ffmpeg ist fehlgeschlagen.")

    mb = os.path.getsize(ziel) / 1024 / 1024
    if mb > 100:
        raise SystemExit(f"{ziel} ist {mb:.0f} MB — Instagram nimmt hoechstens 100 MB.")
    print(f"gerendert: {ziel}  ({gesamt:.0f} s, {mb:.1f} MB)")
    return ziel


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    ziel = sys.argv[2] if len(sys.argv) > 2 else f"videos/post-{spec['post']}.mp4"
    bauen(spec, ziel)
