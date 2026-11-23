# stash-test-server

A real [Stash](https://github.com/stashapp/stash) server, seeded with a
deterministic and fully featured fixture library, for client end-to-end tests
(built for [StashFlow](https://github.com/Alchemist-Aloha/StashFlow)).

All media is **generated with ffmpeg's built-in test sources**: test patterns,
SMPTE bars, gradients, fractals and cellular automata with sine-tone audio. No
third-party footage or photos are included or downloaded, so the library is
royalty-free and safe to publish, cache and redistribute.

## What the profile contains

The whole profile is defined in [`fixtures/profile.json`](fixtures/profile.json).
Client tests should read their expected values from that file, not hard-code them.

| Area | Coverage |
| --- | --- |
| Scenes (10) | H.264 MP4 1080p/720p/1440p, VP9 WebM, MKV, MOV without audio, vertical 720×1280, square 1080×1080, a 480p phash duplicate, untitled/unorganized scenes |
| Scene data | title, code, details, director, date, production date, rating, organized, studio, performers, tags, URLs, group membership with index, O count, play count, resume point, custom fields, stash IDs |
| Markers (3) | point and ranged markers, primary and secondary tags, generated marker previews and screenshots |
| Captions | `en` VTT and `de` SRT on one scene |
| Interactive | `.funscript` scene with a generated heatmap |
| Generated media | covers, previews, WebP previews, sprites and VTT, phashes, image thumbnails |
| Images (20) | JPEG, PNG, WebP, animated GIF, portrait and landscape, with metadata and O count |
| Image clips (2) | an MP4 and the animated GIF, stored as video-backed images (`createImageClipsFromVideos`) |
| Galleries (3) | folder gallery (`.forcegallery`) with chapters, zip gallery, manually created gallery |
| Performers (4) | full field set (measurements, tattoos, piercings, career, circumcision, death date, ...), aliases, favourite, tags, artwork, custom fields, stash IDs; one without an image |
| Studios (3) | parent/child hierarchy, aliases, rating, favourite, logos |
| Tags (11) | parent/child hierarchy, aliases, descriptions, favourite, image, sort name, ignore auto-tag |
| Groups (3) | front/back covers, studio, director, synopsis, sub-groups |
| Saved filters (3) | scenes, performers, images |
| Scrapers | offline `Fixture Scraper` (script scraper in `fixtures/scrapers/`): scene by URL/name/fragment, performer by URL/name/fragment |
| Stash-box | one endpoint (`stashbox.invalid`, unreachable by design) plus stash IDs, for tagger UI; lookups fail |
| Auth | username/password session login **and** an API key; anonymous requests are rejected |

## Use it in GitHub Actions

```yaml
- id: stash
  uses: Alchemist-Aloha/stash-test-server@v1
  # with:
  #   stash-version: v0.31.1   # default: STASH_VERSION file; "latest" also works
  #   port: "9999"

- run: ./run-my-e2e-tests
  env:
    STASH_URL: ${{ steps.stash.outputs.url }}
    STASH_API_KEY: ${{ steps.stash.outputs.api-key }}
    STASH_USERNAME: ${{ steps.stash.outputs.username }}
    STASH_PASSWORD: ${{ steps.stash.outputs.password }}
    STASH_FIXTURE: ${{ steps.stash.outputs.fixture }}
```

The action installs ffmpeg if needed, restores the generated media from the
Actions cache, downloads the Stash release binary, then runs the seeder and
verifier. Expect roughly 2–4 minutes on a cold cache. The API key is masked in
logs, and `stash.log` is printed if any step fails.

## Run it locally

Requires Python 3.10+, ffmpeg/ffprobe and curl.

```bash
scripts/up.sh                 # media → install → start → seed → verify
cat stash-test-server.env     # STASH_URL / STASH_API_KEY / STASH_USERNAME / STASH_PASSWORD
scripts/stop_stash.sh .stash-data
rm -rf .stash-data            # reset to a fresh server
```

Stash runs with an isolated `HOME` under the data directory, so it never
touches your real `~/.stash`. To use Docker instead, see
[`docker/compose.yml`](docker/compose.yml).

## Scripts

| Script | Purpose |
| --- | --- |
| `generate_media.py` | Builds `media/library` and `media/assets`. Skips the work if `MANIFEST.json` is current. |
| `install_stash.sh` | Downloads the Stash release binary for this OS/arch into `bin/`. |
| `start_stash.sh` / `stop_stash.sh` | Run Stash in the background on 127.0.0.1. |
| `seed.py` | First-run setup, scan and generate, entities, metadata, history, credentials and API key. Re-running against a seeded server only refreshes the API key. |
| `verify.py` | Checks counts, auth modes, metadata, duplicate detection and that generated media is served. |

All Python is standard-library only.

## Changing the profile

1. Edit `fixtures/profile.json`. Add media in `generate_media.py` if needed,
   and bump `GENERATOR_VERSION` so CI caches refresh.
2. Update the `expected` block.
3. Run `scripts/up.sh` against a fresh data directory.
4. Tag a new release (`v1.x`) so client repos can pin it.

The weekly CI run also tests against `latest` Stash, to catch API changes
before you bump `STASH_VERSION`.

## License

Scripts: MIT. The generated media is produced entirely by ffmpeg filters and
contains no copyrighted third-party material.
