#!/usr/bin/env python3
"""Seed a fresh Stash server with the fixture profile.

Runs the first-run setup, scans and generates the media library, creates
tags/studios/performers/groups/galleries/markers/saved filters, applies scene
and image metadata, play/O history, then sets credentials and mints an API key.

Paths given with --server-* are as the *server* sees them (they differ from
the local paths when Stash runs in a container).

Outputs (dotenv format) are written to --env-out and, inside GitHub Actions,
appended to $GITHUB_OUTPUT:

    STASH_URL, STASH_API_KEY, STASH_USERNAME, STASH_PASSWORD, STASH_FIXTURE
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stashlib import Stash, StashError, path_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != [] and not k.startswith("$")}


class Seeder:
    def __init__(self, stash: Stash, profile: dict[str, Any], assets: Path) -> None:
        self.s = stash
        self.p = profile
        self.assets = assets
        self.tags: dict[str, str] = {}
        self.studios: dict[str, str] = {}
        self.performers: dict[str, str] = {}
        self.groups: dict[str, str] = {}
        self.scenes: dict[str, str] = {}
        self.images: dict[str, str] = {}

    def img(self, name: str | None) -> str | None:
        return data_url(self.assets / name) if name else None

    # -- server lifecycle ----------------------------------------------
    def setup(self, data_dir: str, library_dir: str) -> None:
        status = self.s.wait_until_up()
        if status["status"] == "SETUP":
            print("running first-run setup")
            self.s.gql(
                "mutation($i: SetupInput!) { setup(input: $i) }",
                {
                    "i": {
                        "configLocation": f"{data_dir}/config.yml",
                        "stashes": [{"path": library_dir, "excludeVideo": False, "excludeImage": False}],
                        "databaseFile": f"{data_dir}/stash-go.sqlite",
                        "generatedLocation": f"{data_dir}/generated",
                        "cacheLocation": f"{data_dir}/cache",
                        "storeBlobsInDatabase": False,
                        "blobsLocation": f"{data_dir}/blobs",
                    }
                },
            )
            status = self.s.wait_until_up()
        if status["status"] == "NEEDS_MIGRATION":
            raise StashError("database needs migration; start from an empty data directory")
        if status["status"] != "OK":
            raise StashError(f"unexpected system status {status}")

    def configure(self, ffmpeg: str | None, ffprobe: str | None) -> None:
        general: dict[str, Any] = {
            "calculateMD5": True,
            "parallelTasks": 0,
            "previewSegments": 6,
            "previewSegmentDuration": 0.75,
            "previewPreset": "ultrafast",
            "previewAudio": True,
            "writeImageThumbnails": True,
            "createGalleriesFromFolders": False,  # only folders with .forcegallery become galleries
        }
        if ffmpeg:
            general["ffmpegPath"] = ffmpeg
        if ffprobe:
            general["ffprobePath"] = ffprobe
        self.s.gql("mutation($i: ConfigGeneralInput!) { configureGeneral(input: $i) { parallelTasks } }", {"i": general})

    def scan_and_generate(self) -> None:
        print("scanning library")
        job = self.s.gql(
            "mutation($i: ScanMetadataInput!) { metadataScan(input: $i) }",
            {
                "i": {
                    "scanGenerateCovers": True,
                    "scanGeneratePreviews": True,
                    "scanGenerateImagePreviews": True,
                    "scanGenerateSprites": True,
                    "scanGeneratePhashes": True,
                    "scanGenerateImagePhashes": True,
                    "scanGenerateThumbnails": True,
                    "scanGenerateClipPreviews": True,
                }
            },
        )["metadataScan"]
        self.s.wait_for_job(job, "scan")
        self.s.wait_for_idle_queue()

    def already_seeded(self) -> bool:
        res = self.s.gql(
            'query { findTags(tag_filter: {name: {value: "Featured", modifier: EQUALS}}) { count } }'
        )
        return res["findTags"]["count"] > 0

    # -- entities ------------------------------------------------------
    def create_tags(self) -> None:
        for t in self.p["tags"]:
            tag = self.s.gql(
                "mutation($i: TagCreateInput!) { tagCreate(input: $i) { id } }",
                {
                    "i": compact(
                        {
                            "name": t["name"],
                            "description": t.get("description"),
                            "aliases": t.get("aliases"),
                            "favorite": t.get("favorite"),
                            "image": self.img(t.get("image")),
                            "parent_ids": [self.tags[n] for n in t.get("parents", [])],
                        }
                    )
                },
            )["tagCreate"]
            self.tags[t["name"]] = tag["id"]
        print(f"created {len(self.tags)} tags")

    def create_studios(self) -> None:
        for st in self.p["studios"]:
            studio = self.s.gql(
                "mutation($i: StudioCreateInput!) { studioCreate(input: $i) { id } }",
                {
                    "i": compact(
                        {
                            "name": st["name"],
                            "parent_id": self.studios.get(st.get("parent", "")),
                            "urls": st.get("urls"),
                            "details": st.get("details"),
                            "favorite": st.get("favorite"),
                            "rating100": st.get("rating100"),
                            "aliases": st.get("aliases"),
                            "tag_ids": [self.tags[n] for n in st.get("tags", [])],
                            "image": self.img(st.get("image")),
                        }
                    )
                },
            )["studioCreate"]
            self.studios[st["name"]] = studio["id"]
        print(f"created {len(self.studios)} studios")

    def create_performers(self) -> None:
        passthrough = (
            "disambiguation", "gender", "birthdate", "country", "height_cm", "eye_color",
            "hair_color", "favorite", "rating100", "alias_list", "urls", "details",
        )
        for pf in self.p["performers"]:
            fields = {k: pf.get(k) for k in passthrough}
            fields.update(
                name=pf["name"],
                tag_ids=[self.tags[n] for n in pf.get("tags", [])],
                image=self.img(pf.get("image")),
            )
            perf = self.s.gql(
                "mutation($i: PerformerCreateInput!) { performerCreate(input: $i) { id } }",
                {"i": compact(fields)},
            )["performerCreate"]
            self.performers[pf["name"]] = perf["id"]
        print(f"created {len(self.performers)} performers")

    def create_groups(self) -> None:
        for g in self.p["groups"]:
            fields = {k: g.get(k) for k in ("date", "director", "synopsis", "duration", "rating100", "urls")}
            fields.update(
                name=g["name"],
                studio_id=self.studios.get(g.get("studio", "")),
                tag_ids=[self.tags[n] for n in g.get("tags", [])],
                front_image=self.img(g.get("front_image")),
                back_image=self.img(g.get("back_image")),
                sub_groups=[
                    compact({"group_id": self.groups[sg["name"]], "description": sg.get("description")})
                    for sg in g.get("sub_groups", [])
                ],
            )
            grp = self.s.gql(
                "mutation($i: GroupCreateInput!) { groupCreate(input: $i) { id } }",
                {"i": compact(fields)},
            )["groupCreate"]
            self.groups[g["name"]] = grp["id"]
        print(f"created {len(self.groups)} groups")

    # -- library objects -----------------------------------------------
    def index_scenes(self) -> None:
        res = self.s.gql("{ findScenes(filter: {per_page: -1}) { scenes { id files { path } } } }")
        for sc in res["findScenes"]["scenes"]:
            for f in sc["files"]:
                key = path_key(f["path"], "scenes")
                if key:
                    self.scenes[key] = sc["id"]
        missing = sorted(set(self.p["scenes"]) - set(self.scenes))
        if missing:
            raise StashError(f"scan did not find scenes: {missing}")

    def index_images(self) -> None:
        res = self.s.gql(
            "{ findImages(filter: {per_page: -1}) { images { id visual_files {"
            " ... on ImageFile { path } ... on VideoFile { path } } } } }"
        )
        for im in res["findImages"]["images"]:
            for f in im["visual_files"]:
                key = path_key(f["path"], "images")
                if key:
                    self.images[key] = im["id"]

    def apply_scenes(self) -> None:
        marker_count = 0
        for key, sc in self.p["scenes"].items():
            sid = self.scenes[key]
            meta = {k: sc.get(k) for k in ("title", "code", "details", "director", "date", "rating100", "organized", "urls")}
            meta.update(
                id=sid,
                studio_id=self.studios.get(sc.get("studio", "")),
                performer_ids=[self.performers[n] for n in sc.get("performers", [])],
                tag_ids=[self.tags[n] for n in sc.get("tags", [])],
                groups=[{"group_id": self.groups[g["name"]], "scene_index": g.get("scene_index")} for g in sc.get("groups", [])],
            )
            meta = compact(meta)
            if len(meta) > 1:
                self.s.gql("mutation($i: SceneUpdateInput!) { sceneUpdate(input: $i) { id } }", {"i": meta})

            for _ in range(sc.get("o_count", 0)):
                self.history("sceneAddO", "sceneIncrementO", sid)
            for _ in range(sc.get("play_count", 0)):
                self.history("sceneAddPlay", "sceneIncrementPlayCount", sid)
            if "resume_time" in sc:
                self.s.gql(
                    "mutation($id: ID!, $t: Float) { sceneSaveActivity(id: $id, resume_time: $t, playDuration: 30) }",
                    {"id": sid, "t": sc["resume_time"]},
                )
            for m in sc.get("markers", []):
                self.s.gql(
                    "mutation($i: SceneMarkerCreateInput!) { sceneMarkerCreate(input: $i) { id } }",
                    {
                        "i": compact(
                            {
                                "scene_id": sid,
                                "title": m["title"],
                                "seconds": m["seconds"],
                                "end_seconds": m.get("end_seconds"),
                                "primary_tag_id": self.tags[m["primary_tag"]],
                                "tag_ids": [self.tags[n] for n in m.get("tags", [])],
                            }
                        )
                    },
                )
                marker_count += 1
        print(f"updated {len(self.p['scenes'])} scenes, created {marker_count} markers")

    def history(self, mutation: str, legacy: str, sid: str) -> None:
        try:
            self.s.gql(f"mutation($id: ID!) {{ {mutation}(id: $id) {{ count }} }}", {"id": sid})
        except StashError:
            self.s.gql(f"mutation($id: ID!) {{ {legacy}(id: $id) }}", {"id": sid})

    def apply_images(self) -> None:
        for key, im in self.p["images"].items():
            iid = self.images[key]
            fields = compact(
                {
                    "id": iid,
                    "title": im.get("title"),
                    "rating100": im.get("rating100"),
                    "studio_id": self.studios.get(im.get("studio", "")),
                    "performer_ids": [self.performers[n] for n in im.get("performers", [])],
                    "tag_ids": [self.tags[n] for n in im.get("tags", [])],
                }
            )
            self.s.gql("mutation($i: ImageUpdateInput!) { imageUpdate(input: $i) { id } }", {"i": fields})
            for _ in range(im.get("o_count", 0)):
                self.s.gql("mutation($id: ID!) { imageIncrementO(id: $id) }", {"id": iid})
        print(f"updated {len(self.p['images'])} images")

    def apply_galleries(self) -> None:
        res = self.s.gql(
            "{ findGalleries(filter: {per_page: -1}) { galleries { id folder { path } files { path } } } }"
        )
        by_key: dict[str, str] = {}
        for g in res["findGalleries"]["galleries"]:
            paths = [g["folder"]["path"]] if g.get("folder") else []
            paths += [f["path"] for f in g.get("files") or []]
            for p in paths:
                key = path_key(p + "/", "images")
                if key:
                    by_key[key.rstrip("/")] = g["id"]

        for gal in self.p["galleries"]:
            fields = {k: gal.get(k) for k in ("title", "date", "details", "rating100", "photographer")}
            fields.update(
                studio_id=self.studios.get(gal.get("studio", "")),
                performer_ids=[self.performers[n] for n in gal.get("performers", [])],
                tag_ids=[self.tags[n] for n in gal.get("tags", [])],
                scene_ids=[self.scenes[k] for k in gal.get("scenes", [])],
            )
            if gal.get("create"):
                gid = self.s.gql(
                    "mutation($i: GalleryCreateInput!) { galleryCreate(input: $i) { id } }",
                    {"i": compact(fields)},
                )["galleryCreate"]["id"]
                self.s.gql(
                    "mutation($i: GalleryAddInput!) { addGalleryImages(input: $i) }",
                    {"i": {"gallery_id": gid, "image_ids": [self.images[k] for k in gal["images"]]}},
                )
            else:
                key = gal.get("folder") or gal.get("zip")
                if key not in by_key:
                    raise StashError(f"scan did not create gallery for {key!r}; found {sorted(by_key)}")
                fields["id"] = by_key[key]
                self.s.gql("mutation($i: GalleryUpdateInput!) { galleryUpdate(input: $i) { id } }", {"i": compact(fields)})
        print(f"configured {len(self.p['galleries'])} galleries")

    def save_filters(self) -> None:
        for f in self.p["saved_filters"]:
            self.s.gql(
                "mutation($i: SaveFilterInput!) { saveFilter(input: $i) { id } }",
                {"i": compact({"mode": f["mode"], "name": f["name"], "find_filter": f.get("find_filter")})},
            )
        print(f"saved {len(self.p['saved_filters'])} filters")

    def generate_derived(self) -> None:
        print("generating marker media, heatmaps and remaining assets")
        job = self.s.gql(
            "mutation($i: GenerateMetadataInput!) { metadataGenerate(input: $i) }",
            {
                "i": {
                    "covers": True,
                    "sprites": True,
                    "previews": True,
                    "imagePreviews": True,
                    "markers": True,
                    "markerImagePreviews": True,
                    "markerScreenshots": True,
                    "phashes": True,
                    "interactiveHeatmapsSpeeds": True,
                    "imagePhashes": True,
                    "imageThumbnails": True,
                    "clipPreviews": True,
                }
            },
        )["metadataGenerate"]
        self.s.wait_for_job(job, "generate")
        self.s.wait_for_idle_queue()

    # -- auth ------------------------------------------------------------
    def secure(self) -> str:
        creds = self.p["credentials"]
        try:
            self.s.gql(
                "mutation($i: ConfigGeneralInput!) { configureGeneral(input: $i) { username } }",
                {"i": {"username": creds["username"], "password": creds["password"]}},
            )
        except StashError as e:
            if "HTTP 401" not in str(e):
                raise  # a 401 means credentials were already set by an earlier run
        self.s.login(creds["username"], creds["password"])
        key = self.s.gql("mutation { generateAPIKey(input: {}) }")["generateAPIKey"]
        probe = Stash(self.s.base_url, api_key=key)
        probe.gql("{ findScenes(filter: {per_page: 1}) { count } }")
        print("credentials set and API key verified")
        return key


def write_outputs(path: Path | None, values: dict[str, str]) -> None:
    lines = "".join(f"{k}={v}\n" for k, v in values.items())
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(lines, encoding="utf-8")
        path.chmod(0o600)
        print(f"wrote {path}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        mapping = {
            "STASH_URL": "url", "STASH_API_KEY": "api-key", "STASH_USERNAME": "username",
            "STASH_PASSWORD": "password", "STASH_FIXTURE": "fixture",
        }
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.writelines(f"{mapping[k]}={v}\n" for k, v in values.items())
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{values['STASH_API_KEY']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:9999")
    ap.add_argument("--profile", type=Path, default=ROOT / "fixtures" / "profile.json")
    ap.add_argument("--assets", type=Path, default=ROOT / "media" / "assets", help="local artwork directory")
    ap.add_argument("--server-data-dir", required=True, help="Stash data directory, as seen by the server")
    ap.add_argument("--server-library-dir", required=True, help="media/library directory, as seen by the server")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"), help="ffmpeg path as seen by the server")
    ap.add_argument("--ffprobe", default=shutil.which("ffprobe"), help="ffprobe path as seen by the server")
    ap.add_argument("--env-out", type=Path, default=ROOT / "stash-test-server.env")
    args = ap.parse_args()

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    stash = Stash(args.url)
    seeder = Seeder(stash, profile, args.assets)
    try:
        status = stash.wait_until_up()
        if status["status"] == "AUTH_REQUIRED":
            print("server already secured; assuming it was seeded earlier")
        else:
            seeder.setup(args.server_data_dir, args.server_library_dir)
            seeder.configure(args.ffmpeg, args.ffprobe)
            if seeder.already_seeded():
                print("fixture entities already present; skipping seeding")
            else:
                seeder.scan_and_generate()
                seeder.create_tags()
                seeder.create_studios()
                seeder.create_performers()
                seeder.create_groups()
                seeder.index_scenes()
                seeder.index_images()
                seeder.apply_scenes()
                seeder.apply_images()
                seeder.apply_galleries()
                seeder.save_filters()
                seeder.generate_derived()
        api_key = seeder.secure()
    except StashError as e:
        sys.exit(f"seeding failed: {e}")

    write_outputs(
        args.env_out,
        {
            "STASH_URL": args.url,
            "STASH_API_KEY": api_key,
            "STASH_USERNAME": profile["credentials"]["username"],
            "STASH_PASSWORD": profile["credentials"]["password"],
            "STASH_FIXTURE": str(args.profile.resolve()),
        },
    )


if __name__ == "__main__":
    main()
