#!/usr/bin/env python3
"""Musik-Konnektor fuer @shortheaven3.

Liefert zu jedem Reel eine lizenzfreie Tonspur in exakt passender Laenge.

Anbieter:
  * "eigen"  - erzeugt die Spur hier, aus Sinusschichten, Rauschen und Hall.
               Standard. Keine fremden Rechte, kein Abruf, keine Ausfaelle,
               und Instagrams Tonerkennung findet nichts zum Anschlagen.
  * "archiv" - nimmt eine geprueft freie Datei aus audio/ im Repo.
               Fuer den Fall, dass spaeter zugekaufte oder CC0-Stuecke
               dazukommen sollen. Lizenznachweis in audio/LIZENZEN.md.

Aufruf:
    python3 musik.py probe.wav 22 "Die Stille" 32
"""
from __future__ import annotations

import json
import os
import sys
import wave

import numpy as np
from scipy import signal

SR = 44100
BASE = os.path.dirname(os.path.abspath(__file__))
ARCHIV = os.path.join(BASE, "audio")

# Grundton, Tonleiter und Dichte je Saeule. Die Stille bekommt am wenigsten.
STIMMUNG = {
    "Der Spiegel": dict(grund=110.00, stufen=(0, 3, 7, 10, 12), glocken=0.55, luft=0.35),
    "Das Ritual":  dict(grund=73.42,  stufen=(0, 2, 7, 9, 14),  glocken=0.70, luft=0.30),
    "Die Frage":   dict(grund=82.41,  stufen=(0, 2, 7, 12, 14), glocken=0.60, luft=0.40),
    "Die Stille":  dict(grund=65.41,  stufen=(0, 7, 12, 15),    glocken=0.28, luft=0.45),
}
STANDARD = STIMMUNG["Die Stille"]


def _halbton(grund: float, n: int) -> float:
    return grund * 2 ** (n / 12)


def _hall(x: np.ndarray, rng, sekunden: float = 2.2, anteil: float = 0.34) -> np.ndarray:
    """Faltungshall aus abklingendem, gefiltertem Rauschen."""
    n = int(sekunden * SR)
    t = np.linspace(0, sekunden, n, dtype=np.float32)
    ir = rng.normal(0, 1, n).astype(np.float32) * np.exp(-t * 2.6)
    sos = signal.butter(2, 2600, "lp", fs=SR, output="sos")
    ir = signal.sosfilt(sos, ir).astype(np.float32)
    ir /= np.abs(ir).max() + 1e-9
    nass = signal.fftconvolve(x, ir)[: len(x)].astype(np.float32)
    nass /= np.abs(nass).max() + 1e-9
    return ((1 - anteil) * x + anteil * nass).astype(np.float32)


def erzeugen(dauer: float, saeule: str = "", seed: int = 0) -> np.ndarray:
    """Ambient-Bett in Stereo, float32, Laenge exakt `dauer` Sekunden."""
    st = STIMMUNG.get(saeule, STANDARD)
    rng = np.random.default_rng(seed or 1)
    n = int(dauer * SR)
    t = np.arange(n, dtype=np.float32) / SR
    links = np.zeros(n, np.float32)
    rechts = np.zeros(n, np.float32)

    # 1) Bordun: Grundton und Quinte, leicht verstimmt, damit es atmet
    for f, amp in ((st["grund"], 0.34), (st["grund"] * 1.4983, 0.19),
                   (st["grund"] * 2, 0.13)):
        for seite, versatz in ((0, -1.0), (1, 1.0)):
            ff = f * (1 + versatz * rng.uniform(0.0006, 0.0022))
            lfo = 0.72 + 0.28 * np.sin(2 * np.pi * rng.uniform(0.03, 0.075) * t
                                       + rng.uniform(0, 6.28))
            welle = np.sin(2 * np.pi * ff * t).astype(np.float32) * lfo * amp
            (links if seite == 0 else rechts)[:] += welle

    # 2) Flaeche: Tonleiterstufen, jede mit eigener langsamer Schwelle
    for stufe in st["stufen"]:
        f = _halbton(st["grund"], stufe) * 2
        phase = rng.uniform(0, 6.28)
        periode = rng.uniform(11.0, 23.0)
        h = np.clip(np.sin(2 * np.pi * t / periode + phase), 0, 1) ** 1.7
        amp = rng.uniform(0.05, 0.10)
        kern = (np.sin(2 * np.pi * f * t) * 0.75
                + np.sin(2 * np.pi * f * 2.002 * t) * 0.17
                + np.sin(2 * np.pi * f * 3.001 * t) * 0.08).astype(np.float32)
        pan = rng.uniform(0.28, 0.72)
        links += kern * h * amp * (1 - pan)
        rechts += kern * h * amp * pan

    # 3) Einzelne Toene, sparsam gesetzt, wie etwas Entferntes
    anzahl = int(dauer * st["glocken"] / 3.4)
    for _ in range(max(0, anzahl)):
        start = rng.uniform(1.5, max(2.0, dauer - 4.0))
        i0 = int(start * SR)
        laenge = int(rng.uniform(2.4, 4.2) * SR)
        laenge = min(laenge, n - i0)
        if laenge <= 0:
            continue
        tt = np.arange(laenge, dtype=np.float32) / SR
        f = _halbton(st["grund"], rng.choice(st["stufen"]) + 24)
        huelle = np.exp(-tt * rng.uniform(1.0, 1.7)).astype(np.float32)
        anschlag = np.clip(tt / 0.06, 0, 1)
        ton = (np.sin(2 * np.pi * f * tt) * 0.8
               + np.sin(2 * np.pi * f * 2.01 * tt) * 0.2).astype(np.float32)
        ton *= huelle * anschlag * rng.uniform(0.05, 0.09)
        pan = rng.uniform(0.2, 0.8)
        links[i0:i0 + laenge] += ton * (1 - pan)
        rechts[i0:i0 + laenge] += ton * pan

    # 4) Luft: sehr leises, tiefpassgefiltertes Rauschen
    sos_luft = signal.butter(2, 1100, "lp", fs=SR, output="sos")
    for kanal in (links, rechts):
        rausch = signal.sosfilt(sos_luft, rng.normal(0, 1, n)).astype(np.float32)
        rausch /= np.abs(rausch).max() + 1e-9
        atem = 0.6 + 0.4 * np.sin(2 * np.pi * 0.045 * t + rng.uniform(0, 6.28))
        kanal += rausch * atem * 0.030 * st["luft"]

    # 5) Waerme, Hall, Blenden, Pegel
    sos_warm = signal.butter(2, 4200, "lp", fs=SR, output="sos")
    links = signal.sosfilt(sos_warm, links).astype(np.float32)
    rechts = signal.sosfilt(sos_warm, rechts).astype(np.float32)
    links = _hall(links, np.random.default_rng(seed + 11))
    rechts = _hall(rechts, np.random.default_rng(seed + 12))

    ein = np.clip(t / 2.6, 0, 1) ** 1.5
    aus = np.clip((dauer - t) / 3.2, 0, 1) ** 1.4
    blende = (ein * aus).astype(np.float32)
    stereo = np.stack([links * blende, rechts * blende], axis=1)

    spitze = np.abs(stereo).max() + 1e-9
    stereo *= (10 ** (-14 / 20)) / spitze          # Spitze auf etwa -14 dBFS
    rms = np.sqrt((stereo ** 2).mean()) + 1e-9
    stereo *= min(1.0, (10 ** (-23 / 20)) / rms)   # Bett, nicht Vordergrund
    return np.clip(stereo, -1, 1).astype(np.float32)


def _aus_archiv(dauer: float, seed: int):
    """Geprueft freie Datei aus audio/ nehmen, falls vorhanden."""
    reg = os.path.join(ARCHIV, "register.json")
    if not os.path.exists(reg):
        return None
    stuecke = json.load(open(reg, encoding="utf-8")).get("stuecke", [])
    stuecke = [s for s in stuecke if os.path.exists(os.path.join(ARCHIV, s["datei"]))]
    if not stuecke:
        return None
    return os.path.join(ARCHIV, stuecke[seed % len(stuecke)]["datei"])


def schreiben(pfad: str, stereo: np.ndarray) -> str:
    daten = (np.clip(stereo, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(pfad, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(daten)
    return pfad


def spur(pfad: str, dauer: float, saeule: str = "", seed: int = 0,
         anbieter: str = "eigen") -> str:
    """Erzeugt die Tonspur und gibt den Dateipfad zurueck."""
    if anbieter == "archiv":
        treffer = _aus_archiv(dauer, seed)
        if treffer:
            return treffer
        print("Archiv leer - erzeuge Spur selbst.")
    return schreiben(pfad, erzeugen(dauer, saeule, seed))


if __name__ == "__main__":
    ziel = sys.argv[1] if len(sys.argv) > 1 else "probe.wav"
    dauer = float(sys.argv[2]) if len(sys.argv) > 2 else 22.0
    saeule = sys.argv[3] if len(sys.argv) > 3 else "Die Stille"
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 32
    print("geschrieben:", spur(ziel, dauer, saeule, seed))
