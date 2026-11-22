#!/usr/bin/env python3
"""Generate the Mongolian voice-over for the guided tour (Дуут тайлбар).

Reads src/ui/tour.json and writes one mp3 per step with Microsoft's Mongolian
neural voices (mn-MN-YesuiNeural = эмэгтэй, mn-MN-BataaNeural = эрэгтэй) through
the free edge-tts package. Needs internet only while generating.

    python3 -m venv ~/.venvs/tts && ~/.venvs/tts/bin/pip install edge-tts
    ~/.venvs/tts/bin/python tools/make_voice.py --preview   # compare voices first
    ~/.venvs/tts/bin/python tools/make_voice.py             # make the whole tour

Voice, speed and pitch come from "settings" in tour.json
(e.g. "mail": {"voice": "mn-MN-YesuiNeural", "rate": "-6%", "pitch": "+0Hz"});
--voice/--rate/--pitch override them.

Output: src/ui/voice/<example>/<NN>.mp3 and src/ui/voice/manifest.json.
The UI plays a file only if the manifest text matches tour.json, so after you
edit the script just run this again (unchanged steps are skipped).
"""
import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "src", "ui")
TOUR = os.path.join(UI, "tour.json")
OUT = os.path.join(UI, "voice")
MANIFEST = os.path.join(OUT, "manifest.json")
VOICES = {"Yesui": "mn-MN-YesuiNeural", "Bataa": "mn-MN-BataaNeural"}


async def synth(text, cfg, path):
    import edge_tts
    tmp = path + ".part"
    for attempt in range(3):            # network hiccups: retry a couple of times
        try:
            await edge_tts.Communicate(text, cfg["voice"], rate=cfg["rate"],
                                       pitch=cfg["pitch"]).save(tmp)
            if os.path.getsize(tmp) == 0:
                raise RuntimeError("хоосон аудио ирлээ")
            os.replace(tmp, path)
            return
        except Exception as e:
            if attempt == 2:
                sys.exit(f"Алдаа ({os.path.basename(path)}): {e}\n"
                         "Интернэт холболтоо шалгаад дахин ажиллуулна уу.")
            await asyncio.sleep(2)


def save_manifest(manifest):
    tmp = MANIFEST + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MANIFEST)


def settings_for(tour, ex, args):
    base = {"voice": tour.get("voice", "mn-MN-YesuiNeural"), "rate": "+0%", "pitch": "+0Hz"}
    base.update(tour.get("settings", {}).get(ex, {}))
    for k in ("voice", "rate", "pitch"):
        if getattr(args, k):
            base[k] = getattr(args, k)
    return base


async def preview(tour, ex, args):
    """Same sentence with both voices and three speeds, to pick by ear."""
    st = tour["themes"][ex][args.step]
    text = st.get("say") or st["text"]
    folder = os.path.join(OUT, "preview")
    os.makedirs(folder, exist_ok=True)
    print(f"Жишээ өгүүлбэр: {text[:80]}…")
    for name, voice in VOICES.items():
        for rate in ("-10%", "-5%", "+0%"):
            path = os.path.join(folder, f"{ex}_{name}_{rate.replace('%', '')}.mp3")
            await synth(text, {"voice": voice, "rate": rate, "pitch": "+0Hz"}, path)
            print("  ", os.path.relpath(path, ROOT))
    print("\nСонсоод таалагдсанаа tour.json-ийн \"settings\" хэсэгт бичнэ, эсвэл:")
    print("  python tools/make_voice.py --force --voice mn-MN-BataaNeural --rate -5%")


async def main(args):
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        sys.exit("edge-tts суугаагүй байна. Debian дээр:\n"
                 "  python3 -m venv ~/.venvs/tts && ~/.venvs/tts/bin/pip install edge-tts\n"
                 "  ~/.venvs/tts/bin/python tools/make_voice.py")

    with open(TOUR, encoding="utf-8") as f:
        tour = json.load(f)
    if args.preview:
        return await preview(tour, args.preview, args)
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = {}

    total = made = 0
    for ex, steps in tour["themes"].items():
        if args.only and ex != args.only:
            continue
        cfg = settings_for(tour, ex, args)
        os.makedirs(os.path.join(OUT, ex), exist_ok=True)
        entries = manifest.get(ex, [])
        entries += [None] * (len(steps) - len(entries))
        entries = entries[:len(steps)]
        print(f"[{ex}] хоолой {cfg['voice']}, хурд {cfg['rate']}, өндөр {cfg['pitch']}")
        for i, st in enumerate(steps):
            total += 1
            text = st.get("say") or st["text"]
            rel = f"{ex}/{i:02d}.mp3"
            path = os.path.join(OUT, ex, f"{i:02d}.mp3")
            want = {"file": rel, "text": text, **cfg}
            if not args.force and entries[i] == want and os.path.isfile(path):
                continue
            print(f"  {rel}  {text[:60]}…")
            await synth(text, cfg, path)
            entries[i] = want
            made += 1
            manifest[ex] = entries
            save_manifest(manifest)      # after every step: an interrupted run keeps its work
        manifest[ex] = entries
        save_manifest(manifest)

    print(f"Бэлэн: {made} шинэ, {total - made} өөрчлөгдөөгүй.")
    print("Одоо python3 src/gui.py ажиллуулаад «Дуут тайлбар» дарна уу.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Дуут тайлбарын mp3 үүсгэх (edge-tts, mn-MN)")
    ap.add_argument("--voice", help="mn-MN-YesuiNeural (эмэгтэй) эсвэл mn-MN-BataaNeural (эрэгтэй)")
    ap.add_argument("--rate", help="ярих хурд, жишээ нь -8%% эсвэл +5%%")
    ap.add_argument("--pitch", help="хоолойн өндөр, жишээ нь -2Hz эсвэл +3Hz")
    ap.add_argument("--only", choices=["mail"], help="зөвхөн нэг жишээ")
    ap.add_argument("--force", action="store_true", help="бүгдийг дахин үүсгэх")
    ap.add_argument("--preview", nargs="?", const="mail", choices=["mail"],
                    help="хоёр хоолой, гурван хурдаар нэг өгүүлбэр үүсгэж харьцуулах")
    ap.add_argument("--step", type=int, default=3, help="--preview-д ашиглах алхмын дугаар")
    asyncio.run(main(ap.parse_args()))
