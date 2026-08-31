#!/usr/bin/env python3
"""Sprachausgabe fuer Reels: liest vor, was auf der Slide steht.

Warum Piper und kein Dienst mit Konto
-------------------------------------
Fuer die Musik gilt in diesem Projekt seit Wochen: selbst erzeugt, kein fremdes
Recht im Spiel, kein API-Abruf, der am Posting-Morgen ausfallen kann. Fuer die
Stimme gilt dasselbe Argument, also dieselbe Antwort.

Piper ist quelloffen (MIT), laeuft ohne Konto, ohne Schluessel und ohne
Kontingent. Das Sprachmodell `de_DE-thorsten-medium` stammt aus dem
Thorsten-Voice-Datensatz, der unter CC0 steht - der Sprecher hat seine Stimme
ausdruecklich freigegeben. Damit ist auch die kommerzielle Nutzung sauber, was
bei einem Konto mit Umsatzabsicht der entscheidende Punkt ist.

Geprueft und verworfen:
- ElevenLabs, HeyGen, LMNT, Typecast: brauchen Konto und haben ein Freikontingent,
  das monatlich ausgeht. Ein Beitrag, der um 05:30 am Kontingent scheitert, ist
  ein ausgefallener Beitrag.
- edge-tts: kostenlos und ohne Konto, spricht aber ueber einen Endpunkt, den
  Microsoft fuer die Vorlesefunktion des Edge-Browsers betreibt. Kein
  dokumentierter oeffentlicher Zugang, jederzeit abschaltbar, und fuer ein Konto
  mit Umsatzabsicht eine Grauzone.

Das Modell wird einmal geholt und im Renderlauf zwischengespeichert. Faellt der
Abruf aus, laeuft das Reel ohne Stimme weiter - stumm ist besser als gar nicht.
"""
from __future__ import annotations

import io
import os
import urllib.request
import wave

import numpy as np

SR = 44100
STIMME = os.environ.get("PIPER_STIMME", "de_DE-thorsten-medium")
QUELLE = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
          "de/de_DE/thorsten/medium/")
ZEITSPERRE = 90


def _holen(url: str, ziel: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shortheaven3-autoposter/1.0"})
        with urllib.request.urlopen(req, timeout=ZEITSPERRE) as r:
            roh = r.read()
        teil = ziel + ".teil"
        with open(teil, "wb") as f:
            f.write(roh)
        os.replace(teil, ziel)
        return True
    except Exception as e:
        print(f"  Stimmmodell nicht geladen ({type(e).__name__}: {e})")
        return False


def modell(ordner: str) -> tuple[str, str] | None:
    """Holt Modell und Konfiguration, wenn sie fehlen. None heisst: keine Stimme."""
    os.makedirs(ordner, exist_ok=True)
    pfade = []
    for endung in (".onnx", ".onnx.json"):
        pfad = os.path.join(ordner, STIMME + endung)
        if not os.path.exists(pfad):
            print(f"  hole {STIMME}{endung}")
            if not _holen(QUELLE + STIMME + endung + "?download=true", pfad):
                return None
        pfade.append(pfad)
    return pfade[0], pfade[1]


def _auf_sr(x: np.ndarray, von: int) -> np.ndarray:
    """Auf 44100 Hz bringen. scipy ist ohnehin Abhaengigkeit des Renderlaufs."""
    if von == SR:
        return x
    from math import gcd

    from scipy.signal import resample_poly
    g = gcd(SR, von)
    return resample_poly(x, SR // g, von // g).astype(np.float32)


def aufnehmen(saetze: list[str], ordner: str) -> list[np.ndarray] | None:
    """Ein Sprachclip je Satz, mono float32 bei 44100 Hz. None heisst: keine Stimme."""
    dateien = modell(ordner)
    if not dateien:
        return None
    try:
        from piper import PiperVoice, SynthesisConfig
    except Exception as e:
        print(f"  piper nicht verfuegbar ({type(e).__name__}: {e})")
        return None
    try:
        voice = PiperVoice.load(dateien[0], dateien[1])
        # Etwas langsamer als die Voreinstellung. Die Saetze sind kurz und sollen
        # nicht gehetzt klingen; das Konto lebt vom ruhigen Ton.
        konf = SynthesisConfig(length_scale=1.18, noise_scale=0.6, noise_w_scale=0.75)
    except Exception as e:
        print(f"  Stimme nicht geladen ({type(e).__name__}: {e})")
        return None

    clips = []
    for satz in saetze:
        puffer = io.BytesIO()
        try:
            with wave.open(puffer, "wb") as w:
                voice.synthesize_wav(satz, w, syn_config=konf)
        except Exception as e:
            print(f"  Satz nicht gesprochen ({type(e).__name__}: {e})")
            return None
        puffer.seek(0)
        with wave.open(puffer, "rb") as w:
            roh = w.readframes(w.getnframes())
            kanaele, rate = w.getnchannels(), w.getframerate()
        x = np.frombuffer(roh, np.int16).astype(np.float32) / 32768.0
        if kanaele > 1:
            x = x.reshape(-1, kanaele).mean(axis=1)
        clips.append(_auf_sr(x, rate))
    return clips


def satz_fuer(slide: dict) -> str:
    """Was vorgelesen wird: genau das, was auf der Slide steht."""
    kopf = (slide.get("headline") or "").strip()
    rumpf = (slide.get("unterzeile") if slide.get("typ") == "hook"
             else slide.get("text", "")) or ""
    if kopf and not kopf.endswith((".", "?", "!", ":")):
        kopf += "."
    return (kopf + " " + rumpf.strip()).strip()


def mischen(musik: np.ndarray, clips: list[np.ndarray], starts: list[float],
            ziel: str) -> str:
    """Sprache ueber die Tonspur legen und die Musik darunter zurueckziehen.

    Ohne Absenkung kaempfen Bordun und Stimme im selben Frequenzbereich und man
    versteht die Haelfte nicht. Die Absenkung laeuft weich an und wieder aus,
    damit kein Pumpen hoerbar wird.
    """
    laenge = musik.shape[0]
    rede = np.zeros(laenge, np.float32)
    for clip, start in zip(clips, starts):
        a = int(start * SR)
        b = min(laenge, a + clip.shape[0])
        if b > a:
            rede[a:b] += clip[:b - a]

    spitze = float(np.max(np.abs(rede))) or 1.0
    rede *= 0.62 / spitze

    # Absenkungshuellkurve: 1 wo nichts gesprochen wird, 0.38 unter der Stimme.
    aktiv = (np.abs(rede) > 0.004).astype(np.float32)
    fenster = int(0.35 * SR)
    kern = np.ones(fenster, np.float32) / fenster
    aktiv = np.clip(np.convolve(aktiv, kern, mode="same") * 3.0, 0, 1)
    huelle = 1.0 - 0.62 * aktiv

    misch = musik * huelle[:, None] + rede[:, None]
    misch = np.clip(misch, -0.985, 0.985)

    with wave.open(ziel, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((misch * 32767).astype(np.int16).tobytes())
    return ziel


def wav_lesen(pfad: str) -> np.ndarray:
    with wave.open(pfad, "rb") as w:
        roh = w.readframes(w.getnframes())
        kanaele = w.getnchannels()
    x = np.frombuffer(roh, np.int16).astype(np.float32) / 32768.0
    return x.reshape(-1, kanaele) if kanaele > 1 else np.stack([x, x], axis=1)
