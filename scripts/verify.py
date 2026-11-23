#!/usr/bin/env python3
"""Check that a seeded Stash server matches fixtures/profile.json.

Verifies entity counts, the authentication modes (API key, session login,
anonymous rejection), key scene metadata, and that generated media (covers,
previews, sprites, VTT, captions, streams, image thumbnails, artwork) is
served. Exits non-zero with a list of failures.

Usage: verify.py [--env stash-test-server.env] [--profile fixtures/profile.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stashlib import Stash, StashError, path_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

SCENE_FIELDS = """
  id title code date rating100 organized interactive o_counter play_count resume_time
  files { path width height video_codec audio_codec duration }
  paths { screenshot preview stream webp vtt sprite funscript interactive_heatmap caption }
  captions { language_code caption_type }
  studio { name }
  performers { name }
  tags { name }
  groups { group { name } scene_index }
  scene_markers { title seconds primary_tag { name } }
"""


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class Checker:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passed = 0

    def check(self, label: str, ok: bool, detail: Any = "") -> None:
        if ok:
            self.passed += 1
        else:
            self.failures.append(f"{label}: {detail}")

    def eq(self, label: str, actual: Any, expected: Any) -> None:
        self.check(label, actual == expected, f"expected {expected!r}, got {actual!r}")


def count(stash: Stash, field: str, arg: str = "filter: {per_page: 0}") -> int:
    return stash.gql(f"{{ {field}({arg}) {{ count }} }}")[field]["count"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", type=Path, default=ROOT / "stash-test-server.env")
    ap.add_argument("--profile", type=Path, default=ROOT / "fixtures" / "profile.json")
    args = ap.parse_args()

    env = load_env(args.env)
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    exp = profile["expected"]
    url = env["STASH_URL"]
    c = Checker()

    # --- authentication modes ------------------------------------------
    anon = Stash(url)
    try:
        anon.gql("{ findScenes(filter: {per_page: 1}) { count } }")
        c.check("anonymous access rejected", False, "request succeeded without credentials")
    except StashError as e:
        c.check("anonymous access rejected", "HTTP 401" in str(e), e)

    session = Stash(url)
    try:
        session.login(env["STASH_USERNAME"], env["STASH_PASSWORD"])
        c.eq("session login scene count", count(session, "findScenes"), exp["scenes"])
    except StashError as e:
        c.check("session login", False, e)

    s = Stash(url, api_key=env["STASH_API_KEY"])

    # --- counts ---------------------------------------------------------
    for field, key in [
        ("findScenes", "scenes"), ("findImages", "images"), ("findGalleries", "galleries"),
        ("findPerformers", "performers"), ("findStudios", "studios"), ("findTags", "tags"),
        ("findGroups", "groups"), ("findSceneMarkers", "scene_markers"),
    ]:
        c.eq(f"{key} count", count(s, field), exp[key])
    c.eq("organized scenes", count(s, "findScenes", "scene_filter: {organized: true}, filter: {per_page: 0}"), exp["organized_scenes"])
    c.eq("interactive scenes", count(s, "findScenes", "scene_filter: {interactive: true}, filter: {per_page: 0}"), exp["interactive_scenes"])
    c.eq("saved filters", len(s.gql("{ findSavedFilters { id } }")["findSavedFilters"]), exp["saved_filters"])

    # --- scene metadata ---------------------------------------------------
    scenes = s.gql(f"{{ findScenes(filter: {{per_page: -1}}) {{ scenes {{ {SCENE_FIELDS} }} }} }}")["findScenes"]["scenes"]
    by_key = {path_key(sc["files"][0]["path"], "scenes"): sc for sc in scenes if sc["files"]}
    c.eq("scenes with captions", sum(1 for sc in scenes if sc.get("captions")), exp["scenes_with_captions"])

    for key, want in profile["scenes"].items():
        sc = by_key.get(key)
        if sc is None:
            c.check(f"scene {key}", False, "missing")
            continue
        if "title" in want:
            c.eq(f"{key} title", sc["title"], want["title"])
        if "rating100" in want:
            c.eq(f"{key} rating", sc["rating100"], want["rating100"])
        if "studio" in want:
            c.eq(f"{key} studio", (sc["studio"] or {}).get("name"), want["studio"])
        if "performers" in want:
            c.eq(f"{key} performers", sorted(p["name"] for p in sc["performers"]), sorted(want["performers"]))
        if "tags" in want:
            c.eq(f"{key} tags", sorted(t["name"] for t in sc["tags"]), sorted(want["tags"]))
        if "o_count" in want:
            c.eq(f"{key} o_counter", sc["o_counter"], want["o_count"])
        if "play_count" in want:
            c.eq(f"{key} play_count", sc["play_count"], want["play_count"])
        if "markers" in want:
            c.eq(f"{key} markers", sorted(m["title"] for m in sc["scene_markers"]), sorted(m["title"] for m in want["markers"]))

    drift = by_key.get("Aurora Pictures/Coastal Drift.mp4")
    if drift:
        c.eq("captions languages", sorted(x["language_code"] for x in drift["captions"] or []), ["de", "en"])
        c.eq("group index", [(g["group"]["name"], g["scene_index"]) for g in drift["groups"]], [("Tidal Trilogy", 1)])
    pulse = by_key.get("Interactive/Pulse Lab.mp4")
    if pulse:
        c.check("Pulse Lab interactive", pulse["interactive"], pulse["interactive"])

    # --- duplicates -------------------------------------------------------
    dupes = s.gql("{ findDuplicateScenes(distance: 8) { files { path } } }")["findDuplicateScenes"]
    dupe_sets = [sorted(path_key(sc["files"][0]["path"], "scenes") or "" for sc in grp) for grp in dupes]
    c.check(
        "phash duplicate pair",
        ["Aurora Pictures/Harbor Lights (480p).mp4", "Aurora Pictures/Harbor Lights.mp4"] in dupe_sets,
        dupe_sets,
    )

    # --- generated media is served -----------------------------------------
    def served(label: str, url_: str | None, ok: Callable[[int], bool] = lambda st: st == 200, rng: str | None = None) -> None:
        if not url_:
            c.check(label, False, "no URL")
            return
        status, body = s.get(url_, byte_range=rng)
        c.check(label, ok(status) and len(body) > 0, f"HTTP {status}, {len(body)} bytes from {url_}")

    if drift:
        p = drift["paths"]
        served("scene screenshot", p["screenshot"])
        served("scene preview", p["preview"])
        served("scene webp", p["webp"])
        served("scene sprite", p["sprite"])
        served("scene vtt", p["vtt"])
        served("scene stream", p["stream"], lambda st: st in (200, 206), rng="bytes=0-1023")
        cap = p["caption"]
        # Stash >= v0.32 returns signed URLs that already carry a query string.
        sep = "&" if cap and "?" in cap else "?"
        served("scene caption", f"{cap}{sep}lang=en&type=vtt" if cap else None)
    if pulse:
        served("interactive heatmap", pulse["paths"]["interactive_heatmap"])

    markers = s.gql("{ findSceneMarkers(filter: {per_page: 1}) { scene_markers { screenshot preview } } }")
    for m in markers["findSceneMarkers"]["scene_markers"]:
        served("marker screenshot", m["screenshot"])
        served("marker preview", m["preview"])

    img = s.gql("{ findImages(filter: {per_page: 1, sort: \"title\"}) { images { paths { thumbnail image } } } }")
    for im in img["findImages"]["images"]:
        served("image thumbnail", im["paths"]["thumbnail"])
        served("image original", im["paths"]["image"])

    perf = s.gql('{ findPerformers(performer_filter: {name: {value: "Mara Quill", modifier: EQUALS}}) { performers { image_path favorite } } }')
    for pf in perf["findPerformers"]["performers"]:
        c.check("Mara Quill favourite", pf["favorite"], pf["favorite"])
        served("performer image", pf["image_path"])

    print(f"{c.passed} checks passed, {len(c.failures)} failed")
    if c.failures:
        print("\n".join(f"  FAIL {f}" for f in c.failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
