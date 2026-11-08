#!/usr/bin/env python3
"""Synthesises the lamp switch's two clicks (owner 2026-11-07). Original sound, made here from a seeded noise burst and
two decaying sine partials -- nothing sampled, nothing to license. Standard library only; run from the repo root:

    python3 scripts/make_lamp_sounds.py

Writes app/CicadaApp/Sources/CicadaApp/Resources/sounds/lamp-on.wav and lamp-off.wav (mono, 16-bit, 22.05 kHz, ~110 ms).
On is a touch brighter and higher; off is lower and a little shorter, so the two can be told apart without looking.
"""
import math, random, struct, wave, pathlib

RATE = 22050
OUT = pathlib.Path("app/CicadaApp/Sources/CicadaApp/Resources/sounds")


def click(seed, body_hz, tick_hz, length, peak):
    rng = random.Random(seed)
    n = int(RATE * length)
    out, lp = [], 0.0
    for i in range(n):
        t = i / RATE
        # the tick: a few ms of noise, low-passed so it is soft rather than sharp
        lp += 0.35 * (rng.uniform(-1, 1) - lp)
        tick = lp * math.exp(-t / 0.0035)
        # the body: the switch's little housing ringing, two partials, fast decay
        body = (math.sin(2 * math.pi * body_hz * t) * 0.7 + math.sin(2 * math.pi * body_hz * 2.31 * t) * 0.3) \
            * math.exp(-t / 0.018)
        tone = math.sin(2 * math.pi * tick_hz * t) * math.exp(-t / 0.006) * 0.4
        attack = min(1.0, t / 0.0008)                      # 0.8 ms in: no pop
        release = min(1.0, (length - t) / 0.02)            # the last 20 ms fade to silence
        out.append((tick * 0.9 + body * 0.8 + tone) * attack * release)
    top = max(abs(s) for s in out)
    return [s / top * peak for s in out]


def write(name, samples):
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s * 32767)) for s in samples))


write("lamp-on.wav", click(1, 880, 2600, 0.11, 0.5))
write("lamp-off.wav", click(2, 600, 1800, 0.10, 0.45))
