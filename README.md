# Alienlist — UAP catalog mirror (war.gov PURSUE Release 01)

Searchable mirror of the U.S. Department of War's first PURSUE declassification (8 May 2026): 161 records across 4 agencies (DoW/AARO, FBI, NASA, State), with a flat satellite map and a visual gallery.

- **Catalog** — `index.html` — sortable/searchable table of every record
- **Map** — `map.html` — pin per record, jittered within each location's regional uncertainty radius
- **Gallery** — `gallery.html` — every visual artifact (FBI A-series stills, B-series PDFs, NASA Apollo lunar photos, the FBI Lab composite sketch)

## Running locally

```bash
python3 -m http.server 5181
# then open http://localhost:5181
```

The 2.4 GB of source PDFs is **not** committed (GitHub's per-file limit is 100 MB). To populate `assets/pdf/` with the full local mirror:

```bash
python3 download.py
```

If `assets/pdf/` is missing, every "Open PDF" link automatically falls back to the war.gov source URL — the deployed site works without a local mirror.

## Files

| Path | Purpose |
|---|---|
| `index.html` / `map.html` / `gallery.html` | the three views |
| `data.js` | catalog + geocode bundle (loaded by all three pages) |
| `catalog.json` | parsed records from `uap-csv.csv` |
| `geocode.json` | lat/lng + uncertainty for each cataloged location |
| `uap-csv.csv` | source CSV mirrored from war.gov/Portals/1/Interactive/2026/UFO/uap-csv.csv |
| `download.py` | parallel downloader for the 2.4 GB PDF mirror |
| `assets/lib/` | self-hosted MapLibre GL JS |
| `assets/thumb/` | 28 MB of catalog thumbnails (committed) |

## Source

All material in this archive is mirrored from <https://www.war.gov/UFO/> as of 8 May 2026. Files are public-domain U.S. government works.
