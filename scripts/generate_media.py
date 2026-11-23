#!/usr/bin/env python3
"""Generate the fixture media library with ffmpeg.

Every video, image and artwork file is synthesised from ffmpeg's built-in
test sources (testsrc2, SMPTE bars, gradients, mandelbrot, life, ...), so the
library contains no third-party content and is free of any licensing or
royalty obligations. Output is deterministic for a given ffmpeg build.

Layout (relative to --out):

    library/scenes/<studio>/<title>.<ext>   video files (+ captions, funscript)
    library/images/...                      loose images, folder gallery, zip gallery
    assets/*.png                            performer/studio/tag/group artwork
    MANIFEST.json                           what was generated, with sizes

Usage: generate_media.py [--out DIR] [--force]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

GENERATOR_VERSION = 1  # bump when output changes; used as a CI cache key


@dataclass(frozen=True)
class Video:
    path: str
    video_src: str
    duration: int
    audio_hz: int | None = 440
    vcodec: str = "h264"
    scale: str | None = None  # optional output size, e.g. "854:480"


VIDEOS = [
    Video("Aurora Pictures/Coastal Drift.mp4", "testsrc2=size=1920x1080:rate=30", 30, 440),
    Video("Aurora Pictures/Harbor Lights.mp4", "smptehdbars=size=1280x720:rate=30,hue=H=2*PI*t/25", 25, 523),
    # Same source as Harbor Lights at a lower resolution: a perceptual-hash duplicate.
    Video(
        "Aurora Pictures/Harbor Lights (480p).mp4",
        "smptehdbars=size=1280x720:rate=30,hue=H=2*PI*t/25",
        25,
        523,
        scale="854:480",
    ),
    Video("Aurora Pictures/Ember Field.mp4", "gradients=size=2560x1440:rate=30:speed=0.02:c0=0x401000:c1=0xff7a00:c2=0xffd000:nb_colors=3", 12, 330),
    Video("Northwind Studio/Prism Study.webm", "rgbtestsrc=size=640x360:rate=30,hue=H=2*PI*t/10", 20, 660, vcodec="vp9"),
    Video("Northwind Studio/Mandelbrot Zoom.mkv", "mandelbrot=size=1280x720:rate=30", 20, 220),
    Video("Northwind Studio/Cellular Bloom.mp4", "life=size=270x270:rate=15:ratio=0.3:mold=20:life_color=0x33ccff:death_color=0x002233:mold_color=0x113355,scale=1080:1080:flags=neighbor,fps=30", 20, 392),
    Video("Vertical/Pocket Garden.mp4", "gradients=size=720x1280:rate=30:speed=0.03:c0=0x0b3d0b:c1=0x7cc46a:c2=0xf2f7a1:nb_colors=3:type=radial", 20, 587),
    Video("Interactive/Pulse Lab.mp4", "zoneplate=size=1280x720:rate=30:kx2=180:ky2=180:kt=25", 20, 494),
    Video("Loose/Silent Grid.mov", "testsrc=size=1280x720:rate=30", 15, None),
]

LOOSE_IMAGES = {
    "sunrise_gradient.jpg": "gradients=size=1920x1080:c0=0x1a0533:c1=0xff6f3c:c2=0xffd27f:nb_colors=3:seed=1",
    "color_bars.png": "smptehdbars=size=1280x720",
    "rings.webp": "zoneplate=size=1024x1024:ku=256:kv=256",
    "noise_tile.png": "cellauto=size=800x800:rule=30:random_seed=7,scale=800:800:flags=neighbor",
    "portrait_frame.jpg": "gradients=size=1080x1920:c0=0x0d1b2a:c1=0x778da9:type=linear:seed=4",
}

OCEAN_COLOURS = [
    ("0x001f3f", "0x0074d9"), ("0x003049", "0x669bbc"), ("0x023e8a", "0x48cae4"),
    ("0x03045e", "0x90e0ef"), ("0x012a4a", "0x2c7da0"), ("0x0a2463", "0x3e92cc"),
    ("0x14213d", "0x8ecae6"), ("0x1b263b", "0xa9d6e5"),
]

ASSETS = {
    "performer_mara.png": "gradients=size=600x900:c0=0x5f0f40:c1=0xfb8b24:type=radial:seed=11",
    "performer_theo.png": "gradients=size=600x900:c0=0x0b132b:c1=0x5bc0be:type=radial:seed=12",
    "performer_iris.png": "gradients=size=600x900:c0=0x3a0ca3:c1=0xf72585:type=radial:seed=13",
    "studio_meridian.png": "gradients=size=512x256:c0=0x222222:c1=0xbbbbbb:seed=21",
    "studio_aurora.png": "gradients=size=512x256:c0=0x00b4d8:c1=0x90e0ef:c2=0xcaf0f8:nb_colors=3:seed=22",
    "studio_northwind.png": "gradients=size=512x256:c0=0x2d6a4f:c1=0xb7e4c7:seed=23",
    "tag_featured.png": "gradients=size=256x256:c0=0xffb703:c1=0xfb8500:type=circular:seed=31",
    "group_tidal_front.png": "gradients=size=600x900:c0=0x03045e:c1=0x00b4d8:seed=41",
    "group_tidal_back.png": "gradients=size=600x900:c0=0x00b4d8:c1=0x03045e:seed=42",
    "group_patterns_front.png": "mandelbrot=size=600x900",
}

VTT = """WEBVTT

00:00:01.000 --> 00:00:05.000
The tide rolls in over the test pattern.

00:00:12.000 --> 00:00:20.000
Wave sequence begins.
"""

SRT = """1
00:00:01,000 --> 00:00:05,000
Die Flut rollt über das Testbild.

2
00:00:12,000 --> 00:00:20,000
Die Wellensequenz beginnt.
"""


def funscript(duration_s: int) -> str:
    actions = [{"at": t * 500, "pos": 0 if t % 2 else 100} for t in range(duration_s * 2)]
    return json.dumps({"version": "1.0", "inverted": False, "range": 100, "actions": actions})


def run(args: list[str]) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"ffmpeg failed ({' '.join(args)}):\n{proc.stderr}")


def still(src: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    extra = ["-q:v", "3"] if out.suffix == ".jpg" else []
    run(["-f", "lavfi", "-i", src, "-frames:v", "1", *extra, str(out)])


def video(v: Video, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-f", "lavfi", "-i", v.video_src]
    if v.audio_hz:
        args += ["-f", "lavfi", "-i", f"sine=frequency={v.audio_hz}:sample_rate=48000"]
    args += ["-t", str(v.duration), "-pix_fmt", "yuv420p"]
    if v.scale:
        args += ["-vf", f"scale={v.scale}"]
    if v.vcodec == "vp9":
        args += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "40", "-deadline", "realtime", "-cpu-used", "8"]
        audio = ["-c:a", "libopus", "-b:a", "64k"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-g", "60"]
        audio = ["-c:a", "aac", "-b:a", "96k"]
    if v.audio_hz:
        args += audio
    if out.suffix in {".mp4", ".mov"}:
        args += ["-movflags", "+faststart"]
    run([*args, str(out)])


def generate(out: Path) -> dict:
    scenes = out / "library" / "scenes"
    images = out / "library" / "images"
    assets = out / "assets"

    for v in VIDEOS:
        video(v, scenes / v.path)

    drift = scenes / "Aurora Pictures" / "Coastal Drift"
    drift.with_name(drift.name + ".en.vtt").write_text(VTT, encoding="utf-8")
    drift.with_name(drift.name + ".de.srt").write_text(SRT, encoding="utf-8")
    (scenes / "Interactive" / "Pulse Lab.funscript").write_text(funscript(20), encoding="utf-8")

    for name, src in LOOSE_IMAGES.items():
        still(src, images / "Loose" / name)
    # Animated GIF: exercises animated-image handling in clients.
    gif = images / "Loose" / "spinner.gif"
    run(["-f", "lavfi", "-i", "testsrc2=size=320x320:rate=12:duration=2", "-vf",
         "split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0", str(gif)])

    ocean = images / "Ocean Studies"
    for i, (c0, c1) in enumerate(OCEAN_COLOURS, start=1):
        still(f"gradients=size=1600x1067:c0={c0}:c1={c1}:seed={100 + i}", ocean / f"ocean_{i:02d}.jpg")
    # Stash turns folders containing this marker file into a gallery.
    (ocean / ".forcegallery").write_text("", encoding="utf-8")

    shapes_tmp = out / ".tmp_shapes"
    shapes = [
        "testsrc2=size=800x800", "rgbtestsrc=size=800x800", "zoneplate=size=800x800:ku=64:kv=64",
        "mandelbrot=size=800x800:start_scale=1.5", "smptehdbars=size=800x800",
    ]
    zpath = images / "Geometry.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_STORED) as zf:
        for i, src in enumerate(shapes, start=1):
            png = shapes_tmp / f"shape_{i:02d}.png"
            still(src, png)
            info = zipfile.ZipInfo(png.name, date_time=(2025, 1, 1, 0, 0, 0))
            zf.writestr(info, png.read_bytes())
    shutil.rmtree(shapes_tmp)

    for name, src in ASSETS.items():
        still(src, assets / name)

    files = sorted(p for p in (out / "library").rglob("*") if p.is_file())
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "files": {str(p.relative_to(out)): p.stat().st_size for p in files},
        "assets": sorted(ASSETS),
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("media"))
    parser.add_argument("--force", action="store_true", help="regenerate even if MANIFEST.json matches")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH")

    manifest_path = args.out / "MANIFEST.json"
    if not args.force and manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("generator_version") == GENERATOR_VERSION and all(
            (args.out / f).exists() for f in existing.get("files", {})
        ):
            print(f"media already generated in {args.out} (use --force to rebuild)")
            return

    if args.out.exists():
        shutil.rmtree(args.out)
    manifest = generate(args.out)
    total = sum(manifest["files"].values())
    print(f"generated {len(manifest['files'])} library files ({total / 1e6:.1f} MB) in {args.out}")


if __name__ == "__main__":
    main()
