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
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import musik

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
def feld(seed: int) -> np.ndarray:
    """Atmosphaerisches Farbfeld, groesser als das Bild, fuer den langsamen Zug."""
    BW, BH = int(W * 1.25), int(H * 1.25)
    rng = np.random.default_rng(seed)
    sw, sh = BW // 4, BH // 4
    a = np.zeros((sh, sw, 3), np.float32) + np.array(BG, np.float32)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    for _ in range(5):
        cx, cy = rng.uniform(0.1, 0.9) * sw, rng.uniform(0.1, 0.9) * sh
        r = rng.uniform(0.30, 0.68) * sw
        warm = rng.uniform(0, 1) < 0.45
        col = np.array(FG if warm else (44, 58, 86), np.float32)
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        m = np.clip(1.0 - d, 0, 1) ** 2.4 * (0.16 if warm else 0.42)
        a += m[..., None] * (col - a) * 0.9
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(15))
    a = np.asarray(im.resize((BW, BH), Image.BICUBIC)).astype(np.float32)

    vw, vh = BW // 8, BH // 8
    yy, xx = np.mgrid[0:vh, 0:vw].astype(np.float32)
    d = np.sqrt(((xx - vw / 2) / (vw / 2)) ** 2 + ((yy - vh / 2) / (vh / 2)) ** 2)
    v = np.clip(1.15 - 0.55 * d, 0.32, 1.0)
    v = np.asarray(Image.fromarray((v * 255).astype(np.uint8)).resize(
        (BW, BH), Image.BICUBIC)).astype(np.float32) / 255.0
    return np.clip(a * v[..., None], 0, 255).astype(np.uint8)


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
def zeiten(slides: list) -> list[float]:
    """Kuerzere Standzeiten, wenn viele Slides kommen — sonst wird das Reel zaeh."""
    lang = len(slides) > 4
    kopf, mitte = (5.5, 4.5) if lang else (6.0, 5.0)
    return [kopf if s.get("typ") in ("hook", "cta") else mitte for s in slides]


def ease(t):
    return t * t * (3 - 2 * t)


def bauen(spec: dict, ziel: str) -> str:
    slides = spec["slides"]
    dauer = zeiten(slides)
    gesamt = sum(dauer)
    nr = spec["post"]

    os.makedirs(os.path.dirname(os.path.abspath(ziel)) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        ton = musik.spur(os.path.join(tmp, "ton.wav"), gesamt,
                         spec.get("saeule", ""), seed=nr,
                         anbieter=os.environ.get("MUSIK_ANBIETER", "eigen"))

        felder = [feld(nr * 100 + i) for i in range(len(slides))]
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

        k = 0
        for si, (sl, dur) in enumerate(zip(slides, dauer)):
            n = int(dur * FPS)
            bg, tx = felder[si], ebenen[si]
            BH, BW = bg.shape[:2]
            for f in range(n):
                t = f / n
                z = 1.0 - 0.055 * t
                cw, ch = int(W * z * 1.25), int(H * z * 1.25)
                ox = int((BW - cw) * (0.5 + 0.10 * (t - 0.5)))
                oy = int((BH - ch) * (0.5 - 0.14 * (t - 0.5)))
                frame = np.asarray(
                    Image.fromarray(bg[oy:oy + ch, ox:ox + cw]).resize(
                        (W, H), Image.BILINEAR)).astype(np.float32)
                tin, tout = 0.75 / dur, 0.55 / dur
                a = (ease(min(1.0, t / tin)) if t < tin
                     else ease(max(0.0, (1 - t) / tout)) if t > 1 - tout else 1.0)
                if a > 0.003:
                    rise = int(26 * (1 - a))
                    lay = np.roll(tx, rise, axis=0) if rise else tx
                    al = (lay[..., 3:4] / 255.0) * a
                    frame = frame * (1 - al) + lay[..., :3] * al
                frame += korn[k % 10]
                k += 1
                p.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
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
