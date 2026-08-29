# Installation / Setup

This document lists every file **loaded by `main.js`** at runtime, what it is
used for, and how to (re)generate the data files. The app is a static web page
(no build step) — it only needs a local web server because it uses `fetch()`.

---

## 1. Files loaded by `main.js`

### Local data / asset files (served from the project root)

| File | Loaded at | Purpose |
|------|-----------|---------|
| `index.html` | — | App entry page; includes `main.js` and the three.js library |
| `main.js` | — | The application itself |
| `geo.json` | `main.js:65` | Country borders, lakes, populated places (Natural Earth, via `fetch_geo.py`) |
| `countries.json` | `main.js:66` | Country polygons used by the legend / country-query (Natural Earth, via `build_countries.py`) |
| `river_plus.json` | `main.js:67` | Extra river-information overlay (via `build_river_plus.py`) |
| `conf.yaml` | `main.js:56` | App configuration (utf-8): `rivers` list, `languages` (→ `texts_<lang>.csv`), `cities` (altitude, people, marker size) |
| `texts_de.csv` | `main.js:96` | UI texts in the configured language (`texts_<lang>.csv`; `de` is `default`) |
| `river_cities.csv` | `main.js:79` | City markers: `river,name,lon,lat,mouth`. Height & population come from `conf.yaml` (`cities`) |
| `rhein.json` | `main.js:84` | Rhein geometry + elevation (`RIVERS` from `conf.yaml`) |
| `rhone.json` | `main.js:84` | Rhône geometry + elevation |
| `aare.json` | `main.js:84` | Aare geometry + elevation |
| `reuss.json` | `main.js:84` | Reuss geometry + elevation |
| `ticino.json` | `main.js:84` | Ticino geometry + elevation |
| `po.json` | `main.js:84` | Po geometry + elevation |
| `river_contours.json` | `main.js:1058` | Rhein isolines (100 m) along the river |
| `rhone_contours.json` | `main.js:1058` | Rhône isolines |
| `aare_contours.json` | `main.js:1058` | Aare isolines |
| `reuss_contours.json` | `main.js:1058` | Reuss isolines |
| `ticino_contours.json` | `main.js:1058` | Ticino isolines |
| `po_contours.json` | `main.js:1058` | Po isolines |
| `europe_opentopomap.tif` | `main.js:503` | Relief/terrain texture drawn under the map (OpenTopoMap-derived GeoTIFF) |

> The `<key>.json` / `<key>_contours.json` pairs are driven by the `rivers` list
> in `conf.yaml` (loaded at `main.js:56`). Add a river there to load it.
> Cities no longer store altitude/population in the CSV — those live in
> `conf.yaml` under `cities`.

### Remote / network dependencies (fetched live)

| Resource | Loaded at | Purpose |
|----------|-----------|---------|
| three.js (CDN) | `index.html` | 3D rendering library |
| OpenTopoMap tiles | `main.js:482` (`loadTile`) | Background map tiles (cached in `CacheStorage`); optional |
| Wikidata SPARQL | `main.js:358` | Waterfall / POI lookups |
| PEGEL online API | `main.js:375` | River gauge stations (`waters=RHEIN`) |

These need internet access; everything in section 1 is fully local.

---

## 2. Running the app

Because the page uses `fetch()` on local files, open it through a web server
(not `file://`):

```powershell
# from the project root
python -m http.server 8000
# then open http://localhost:8000/
```

No compilation or `npm install` is required (three.js is loaded from a CDN).

---

## 3. Generating / refreshing the data files

The data files above are produced by the Python scripts in this repo (run inside
the `.venv` that has `rasterio` + `numpy`):

```powershell
.venv\Scripts\activate

# Base geodata
python fetch_geo.py              # -> geo.json
python build_countries.py        # -> countries.json
python build_river_plus.py       # -> river_plus.json

# Per river (geometry + elevation)
python fetch_river.py --key rhein  --out rhein.json
python fetch_river.py --key rhone  --out rhone.json
python fetch_river.py --key aare   --out aare.json
python fetch_river.py --key reuss  --out reuss.json
python fetch_river.py --key ticino --out ticino.json
python fetch_river.py --key po     --out po.json

# Per river (elevation isolines; needs FABDEM tiles in dem/)
python contour.py rhein.json  100 500 3000 --out river_contours.json
python contour.py rhone.json  100 500 3000 --out rhone_contours.json
python contour.py aare.json   100 500 3000 --out aare_contours.json
python contour.py reuss.json  100 500 3000 --out reuss_contours.json
python contour.py ticino.json 100 500 3000 --out ticino_contours.json
python contour.py po.json     100 500 3000 --out po_contours.json

# Cities (manual edit, no script)
#   edit river_cities.csv
```

FABDEM tiles for `contour.py` are downloaded into `dem/` — see
`howtocreateariver.md` for the exact tile-URL scheme and the full per-river
pipeline (also covers adding *new* rivers).

---

## 4. Directory layout (essentials)

```
.
├── index.html
├── main.js                 # app
├── geo.json                # borders / lakes / cities
├── countries.json          # country polygons
├── river_plus.json        # extra river info
├── river_cities.csv        # city markers (manual)
├── rhein.json / river_contours.json
├── rhone.json / rhone_contours.json
├── aare.json / aare_contours.json
├── reuss.json / reuss_contours.json
├── ticino.json / ticino_contours.json
├── po.json / po_contours.json
├── europe_opentopomap.tif  # terrain texture
├── dem/                    # FABDEM tiles (input to contour.py)
├── *.py                    # data build scripts
└── howtocreateariver.md    # how to add a new river
```
