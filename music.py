"""
Background music for the deal videos.

If the music/ folder has .mp3/.m4a/.wav files (royalty-free tracks you're allowed to
use commercially, e.g. from the YouTube Audio Library), one is picked at random.
Otherwise a short, upbeat, original track is composed on the spot, so every video
has sound and nothing can be copyright-claimed.

  python music.py            writes videos/music-sample.wav to listen to
"""

import random
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
MUSIC_DIR = ROOT / "music"
SR = 44100

# Chord progressions as scale degrees (0 = I). Bright pop / lo-fi shapes.
PROGRESSIONS = [
    [0, 4, 5, 3],   # I V vi IV
    [0, 5, 3, 4],   # I vi IV V
    [5, 3, 0, 4],   # vi IV I V
    [0, 3, 4, 3],   # I IV V IV
    [3, 0, 4, 5],   # IV I V vi
]
MAJOR = [0, 2, 4, 5, 7, 9, 11]


def note_hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def chord_notes(root_midi, degree):
    """Triad (plus 7th for colour) built on a scale degree of the major key."""
    idx = [degree, degree + 2, degree + 4, degree + 6]
    return [root_midi + MAJOR[i % 7] + 12 * (i // 7) for i in idx]


def env(n, attack, decay):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-t / decay)


def tone(hz, n, harmonics=(1.0, 0.35, 0.15), detune=0.0):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k, amp in enumerate(harmonics, 1):
        out += amp * np.sin(2 * np.pi * hz * k * t)
        if detune:
            out += amp * 0.6 * np.sin(2 * np.pi * hz * k * (1 + detune) * t)
    return out


def add(buf, x, start):
    if start >= len(buf):
        return
    end = min(len(buf), start + len(x))
    buf[start:end] += x[: end - start]


def compose(seconds, seed=None):
    rng = random.Random(seed)
    bpm = rng.choice([100, 104, 108, 112, 116])
    beat = 60 / bpm
    n = int(seconds * SR)
    key = rng.choice([57, 58, 60, 62, 64, 65])  # A3 .. F4 roots
    prog = rng.choice(PROGRESSIONS)
    arp_shape = rng.choice([[0, 1, 2, 3, 2, 1, 0, 2], [0, 2, 1, 3, 0, 2, 1, 3], [0, 1, 2, 1, 3, 2, 1, 2]])

    pad = np.zeros(n); arp = np.zeros(n); bass = np.zeros(n); drums = np.zeros(n)
    bar = 4 * beat
    bars = int(seconds / bar) + 2
    noise = np.random.default_rng(seed if isinstance(seed, int) else None)

    for b in range(bars):
        notes = chord_notes(key, prog[b % len(prog)])
        s0 = int(b * bar * SR)
        bar_n = int(bar * SR)
        # warm pad: soft chord held for the bar
        p = sum(tone(note_hz(m), bar_n, (1.0, 0.2), detune=0.003) for m in notes[:3])
        fade = np.minimum(1, np.minimum(np.arange(bar_n) / (0.15 * SR), (bar_n - np.arange(bar_n)) / (0.1 * SR)))
        add(pad, p * fade, s0)
        # plucky 8th-note arpeggio an octave up
        for i, d in enumerate(arp_shape):
            st = s0 + int(i * beat / 2 * SR)
            ln = int(beat * 0.9 * SR)
            add(arp, tone(note_hz(notes[d] + 12), ln, (1.0, 0.45, 0.2)) * env(ln, 0.004, 0.18), st)
        # bass on beats 1 and 3 (+ a pickup on the "and" of 4)
        for pos in (0, 2, 3.5):
            st = s0 + int(pos * beat * SR)
            ln = int(beat * (0.45 if pos == 3.5 else 1.4) * SR)
            add(bass, tone(note_hz(notes[0] - 24), ln, (1.0, 0.5, 0.25)) * env(ln, 0.006, 0.35), st)
        # drums: kick 1 & 3, clap 2 & 4, hats on 8ths
        for k in range(4):
            st = s0 + int(k * beat * SR)
            if k in (0, 2):
                ln = int(0.25 * SR)
                t = np.arange(ln) / SR
                f = 50 + 90 * np.exp(-t * 40)
                add(drums, 0.9 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14), st)
            else:
                ln = int(0.18 * SR)
                add(drums, 0.35 * noise.standard_normal(ln) * env(ln, 0.002, 0.05), st)
        for h in range(8):
            st = s0 + int(h * beat / 2 * SR)
            ln = int(0.05 * SR)
            hat = noise.standard_normal(ln)
            hat = np.diff(hat, prepend=0)  # crude high-pass
            add(drums, (0.10 if h % 2 else 0.06) * hat * env(ln, 0.001, 0.015), st)

    def norm(x):
        m = np.max(np.abs(x)) or 1
        return x / m

    mix = 0.30 * norm(pad) + 0.32 * norm(arp) + 0.40 * norm(bass) + 0.45 * norm(drums)
    # gentle fade in / out
    fi, fo = int(0.03 * SR), int(0.9 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)
    mix[-fo:] *= np.linspace(1, 0, fo)
    mix = norm(mix) * 0.6   # leave headroom; it's background music
    return mix


def write_wav(samples, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stereo = np.repeat((samples * 32767).astype(np.int16)[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(stereo.tobytes())
    return path


def music_for_video(seconds, out_path, seed=None):
    """Returns a path to an audio file to use as the video's soundtrack."""
    tracks = [p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")] \
        if MUSIC_DIR.exists() else []
    if tracks:
        return random.Random(seed).choice(tracks)
    return write_wav(compose(seconds, seed), out_path)


if __name__ == "__main__":
    print("Wrote", write_wav(compose(12, seed=7), ROOT / "videos" / "music-sample.wav"))
