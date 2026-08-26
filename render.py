#!/usr/bin/env python3
"""Rendert Karussell-Slides fuer @shortheaven3 und traegt den Post in schedule.json ein.

Aufruf:  python3 render.py queue/post-31.json
         python3 render.py --alle          (alle Dateien in queue/)

Design-Spezifikation: 1080x1350, #1B2336 mit #9E826A, EB Garamond 12.
"""
import glob
import json
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFont

# Formatmuster ueber acht Beitraege. Strikte Alternation ginge nicht:
# die Saeulen drehen sich im Viererzyklus, ein Zweierwechsel teilt den glatt
# und jede Saeule bekaeme fuer immer dasselbe Format. Dieses Muster gibt
# jeder Saeule beide Formate; dafuer stehen zweimal je acht Beitraege zwei
# gleiche nebeneinander.
FORMATMUSTER = ("reel", "karussell", "reel", "karussell",
                "karussell", "reel", "karussell", "reel")


def format_fuer(spec):
    """Vorgabe aus der Queue schlaegt das Muster."""
    gewuenscht = (spec.get("format") or "").strip().lower()
    if gewuenscht in ("reel", "karussell"):
        return gewuenscht
    return FORMATMUSTER[spec["post"] % len(FORMATMUSTER)]


W, H, CX = 1080, 1350, 540
BG = (27, 35, 54)
FG = (158, 130, 106)
BASE = os.path.dirname(os.path.abspath(__file__))

SUCHORTE = [os.path.join(BASE, "fonts"), "/usr/share/fonts", "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts")]


def font_pfad(muster):
    """Sucht die erste passende Schriftdatei; Muster in absteigender Vorliebe."""
    for m in muster:
        for ort in SUCHORTE:
            for endung in (".ttf", ".otf"):
                treffer = sorted(glob.glob(os.path.join(ort, "**", m + endung), recursive=True))
                if treffer:
                    return treffer[0]
    raise SystemExit(
        "EB Garamond nicht gefunden. Debian/Ubuntu: apt-get install fonts-ebgaramond"
    )


ITALIC = None
REGULAR = None


def font(pfad, size):
    return ImageFont.truetype(pfad, size)


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if draw.textlength(probe, font=fnt) <= max_w or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_block(draw, lines, fnt, y_top, leading):
    for i, line in enumerate(lines):
        draw.text((CX, y_top + i * leading), line, font=fnt, fill=FG, anchor="ma")
    return y_top + len(lines) * leading


def tracked(draw, text, fnt, y, tracking):
    widths = [draw.textlength(c, font=fnt) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = CX - total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=fnt, fill=FG, anchor="la")
        x += w + tracking


def grain(img, seed):
    rnd = random.Random(seed)
    px = img.load()
    for _ in range(int(W * H * 0.06)):
        x, y = rnd.randrange(W), rnd.randrange(H)
        d = rnd.randint(-9, 9)
        r, g, b = px[x, y]
        px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    return img


def rule(draw, y):
    draw.rectangle([490, y, 589, y + 1], fill=FG)


def render_slide(slide, seed):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    typ = slide.get("typ", "inhalt")

    if typ == "hook":
        f_head = font(ITALIC, 74)
        lines = wrap(d, slide["headline"], f_head, 800)
        y_head = 535 - max(0, len(lines) - 2) * 37
        end = draw_block(d, lines, f_head, y_head, 74)
        if slide.get("unterzeile"):
            f_sub = font(ITALIC, 45)
            draw_block(d, wrap(d, slide["unterzeile"], f_sub, 740), f_sub, max(718, end + 30), 56)
        tracked(d, "WISCHEN  →", font(REGULAR, 21), 1183, 3)

    elif typ == "cta":
        f_head = font(ITALIC, 64)
        draw_block(d, wrap(d, slide["headline"], f_head, 820), f_head, 392, 71)
        rule(d, 630)
        f_txt = font(ITALIC, 40)
        draw_block(d, wrap(d, slide.get("text", ""), f_txt, 760), f_txt, 726, 48)
        tracked(d, "@SHORTHEAVEN3", font(REGULAR, 21), 1183, 3)

    else:
        if slide.get("ziffer"):
            tracked(d, slide["ziffer"], font(REGULAR, 16), 159, 5)
        f_head = font(ITALIC, 64)
        draw_block(d, wrap(d, slide["headline"], f_head, 820), f_head, 392, 71)
        rule(d, 630)
        f_txt = font(ITALIC, 40)
        draw_block(d, wrap(d, slide.get("text", ""), f_txt, 760), f_txt, 726, 48)

    return grain(img, seed)


def eintragen(spec, medien, art):
    pfad = os.path.join(BASE, "schedule.json")
    plan = json.load(open(pfad, encoding="utf-8"))
    eintrag = {
        "date": spec["date"],
        "post": spec["post"],
        "saeule": spec.get("saeule", ""),
        "vorlage": "dunkel",
        "format": art,
        "caption": spec["caption"],
        "published_id": None,
    }
    if art == "reel":
        eintrag["video"] = medien
    else:
        eintrag["images"] = medien
    for i, p in enumerate(plan["posts"]):
        if p["post"] == spec["post"]:
            if p.get("published_id"):
                print(f"Post {spec['post']} bereits veroeffentlicht - schedule.json unveraendert.")
                return
            plan["posts"][i] = eintrag
            break
    else:
        plan["posts"].append(eintrag)
    plan["posts"].sort(key=lambda p: p["date"])
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"schedule.json: Post {spec['post']} fuer {spec['date']} eingetragen.")


def schon_veroeffentlicht(nr):
    """Verhindert, dass ein laengst gepostetet Beitrag neu gerendert wird."""
    pfad = os.path.join(BASE, "schedule.json")
    if not os.path.exists(pfad):
        return False
    plan = json.load(open(pfad, encoding="utf-8"))
    return any(p["post"] == nr and p.get("published_id") for p in plan["posts"])


def verarbeiten(pfad):
    spec = json.load(open(pfad, encoding="utf-8"))
    nr = spec["post"]
    if schon_veroeffentlicht(nr):
        print(f"Beitrag {nr} ist veroeffentlicht - uebersprungen.")
        return
    art = format_fuer(spec)
    print(f"Beitrag {nr}: Format {art}")

    if art == "reel":
        import render_reel  # erst hier, damit Karussell-Laeufe ohne numpy/scipy gehen
        name = f"post-{nr}.mp4"
        render_reel.bauen(spec, os.path.join(BASE, "videos", name))
        eintragen(spec, name, art)
        return

    out_dir = os.path.join(BASE, "images")
    os.makedirs(out_dir, exist_ok=True)
    namen = []
    for i, slide in enumerate(spec["slides"], 1):
        name = f"post-{nr}-slide-{i}.jpg"
        render_slide(slide, seed=nr * 100 + i).save(
            os.path.join(out_dir, name), "JPEG", quality=92, subsampling=0
        )
        namen.append(name)
        print("gerendert:", name)
    eintragen(spec, namen, art)


def main():
    global ITALIC, REGULAR
    ITALIC = font_pfad(["EBGaramond12-Italic", "EBGaramond08-Italic", "EBGaramond-Italic",
                        "EBGaramond*Italic"])
    REGULAR = font_pfad(["EBGaramond12-Regular", "EBGaramond08-Regular", "EBGaramond-Regular",
                         "EBGaramond*Regular"])
    print("Schriften:", ITALIC, REGULAR)
    args = sys.argv[1:]
    dateien = sorted(glob.glob(os.path.join(BASE, "queue", "*.json"))) if (
        not args or args[0] == "--alle"
    ) else args
    if not dateien:
        print("Nichts zu rendern.")
        return
    for f in dateien:
        verarbeiten(f)


if __name__ == "__main__":
    main()
