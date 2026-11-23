#!/usr/bin/env python3
"""Stash script scraper that answers from ../profile.json (stdlib only).

Usage (by Stash): fixture_scraper.py <mode>, with the scrape input as JSON on
stdin and the result as JSON on stdout. Scraped details are prefixed with
"Scraped: " so clients can tell scraped values from stored ones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROFILE = json.loads((Path(__file__).resolve().parent.parent / "profile.json").read_text(encoding="utf-8"))


def scene_out(sc: dict) -> dict:
    return {
        "title": sc.get("title"),
        "code": sc.get("code"),
        "details": f"Scraped: {sc.get('details') or sc.get('title')}",
        "director": sc.get("director"),
        "date": sc.get("date"),
        "urls": sc.get("urls", []),
        "studio": {"name": sc["studio"]} if sc.get("studio") else None,
        "performers": [{"name": n} for n in sc.get("performers", [])],
        "tags": [{"name": n} for n in sc.get("tags", [])],
    }


def performer_out(pf: dict) -> dict:
    keys = ("name", "disambiguation", "birthdate", "country", "eye_color", "hair_color",
            "ethnicity", "measurements", "tattoos", "piercings", "urls")
    out = {k: pf[k] for k in keys if k in pf}
    if "gender" in pf:
        out["gender"] = pf["gender"]
    if "alias_list" in pf:
        out["aliases"] = ", ".join(pf["alias_list"])
    if "height_cm" in pf:
        out["height"] = str(pf["height_cm"])
    out["details"] = f"Scraped: {pf.get('details') or pf['name']}"
    return out


def titled_scenes() -> list[dict]:
    return [sc for sc in PROFILE["scenes"].values() if sc.get("title")]


def find_scene(inp: dict) -> dict | None:
    url = inp.get("url")
    title = (inp.get("title") or inp.get("name") or "").lower()
    for sc in titled_scenes():
        if url and url in sc.get("urls", []):
            return sc
        if title and sc["title"].lower() == title:
            return sc
    return None


def find_performer(inp: dict) -> dict | None:
    url = inp.get("url")
    name = (inp.get("name") or "").lower()
    for pf in PROFILE["performers"]:
        if url and url in pf.get("urls", []):
            return pf
        if name and pf["name"].lower() == name:
            return pf
    return None


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = sys.stdin.read()
    inp = json.loads(raw) if raw.strip() else {}
    if mode == "sceneByName":
        q = (inp.get("name") or "").lower()
        result: object = [scene_out(sc) for sc in titled_scenes() if q in sc["title"].lower()]
    elif mode in ("sceneByURL", "sceneByFragment"):
        sc = find_scene(inp)
        result = scene_out(sc) if sc else None
    elif mode == "performerByName":
        q = (inp.get("name") or "").lower()
        result = [performer_out(pf) for pf in PROFILE["performers"] if q in pf["name"].lower()]
    elif mode in ("performerByURL", "performerByFragment"):
        pf = find_performer(inp)
        result = performer_out(pf) if pf else None
    else:
        sys.exit(f"unknown mode {mode!r}")
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
