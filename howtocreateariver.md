# How to create a river

This documents the full data pipeline to produce all files required for a new
river so it can later be wired into the app. It is based on the existing
scripts in this repository (`fetch_river.py`, `contour.py`, `download_fabdem.py`,
`smooth_river.py`, `build_countries.py`).

> Scope of this file: **generate the data files only**. Registering the river in
> the app (selector, RIVERS array) is the *later* step described at the end.

---

## 1. Files produced per river

| File | Contents | Producer |
|------|----------|----------|
| `<key>.json` | River geometry (OSM ways) + elevation per point, source/mouth, length, elev_min/max | `fetch_river.py` |
| `<key>_contours.json` | Smoothed elevation isolines (100 m) only along the river corridor | `contour.py` |
| (rows in `river_cities.csv`) | Cities along the river: `river,name,pop,lon,lat,alt` | manual |

The `<key>` is a short id, e.g. `inn`, `saone`, `doubs`, `donau`. It must match
the `river` column in `river_cities.csv` and the `key` used later in `main.js`.

---

## 2. Prerequisites

- A Python virtual environment with `rasterio` and `numpy`. One already exists:

  ```powershell
  .venv\Scripts\activate
  # if missing: python -m venv .venv ; pip install rasterio numpy
  ```

- Network access to:
  - Overpass API (OpenStreetMap river geometry)
  - Hugging Face (FABDEM elevation tiles)
  - Open-Meteo (fallback elevations if no FABDEM tiles)

Run all commands from the project root (same folder as `main.js`).

---

## 3. Step 1 — Get FABDEM elevation tiles

`contour.py` **requires** FABDEM GeoTIFFs in a `dem/` folder. (If they are
missing, `fetch_river.py` still works but falls back to Open-Meteo elevations;
`contour.py` will abort without tiles.)

Download the 1° tiles that cover your river's bounding box. Reuse the same URL
scheme as `download_fabdem.py`:

```powershell
python -c "
import math, os, urllib.request
BASE='https://huggingface.co/datasets/pavelzaitsau/fabdem-v12/resolve/main/tiles'
os.makedirs('dem', exist_ok=True)
# --- set your river's bounding box here ---
lon_min, lon_max, lat_min, lat_max = 6.0, 14.0, 45.0, 49.0
for latb in range(math.floor(lat_min), math.floor(lat_max)+1):
    for lonb in range(math.floor(lon_min), math.floor(lon_max)+1):
        lat0=(latb//10)*10; lon0=(lonb//10)*10
        folder=f'N{lat0:02d}E{lon0:03d}-N{lat0+10:02d}E{lon0+10:03d}_FABDEM_V1-2'
        fname=f'N{latb:02d}E{lonb:03d}_FABDEM_V1-2.tif'
        out=os.path.join('dem', fname)
        if os.path.exists(out): continue
        url=f'{BASE}/{folder}/{fname}'
        urllib.request.urlretrieve(url, out)
        print('downloaded', fname)
"
```

Adjust the bounding box so it covers the whole river (add a margin of ~1°).

---

## 4. Step 2 — River geometry → `<key>.json`

`fetch_river.py` downloads the OSM relation, stitches its ways into a
source→mouth path, and samples elevations (FABDEM preferred, Open-Meteo fallback).

```powershell
python fetch_river.py --names "Inn"            --source 9.69,46.46  --mouth 13.469,48.574 --out inn.json
python fetch_river.py --names "Saône","La Saône" --source 5.04,47.32 --mouth 4.835,45.757 --out saone.json
python fetch_river.py --names "Doubs"          --source 6.20,46.68  --mouth 5.04,46.95    --out doubs.json
python fetch_river.py --names "Donau","Danube" --source 8.134,47.953 --mouth 19.04,47.498  --out donau.json
```

- `--names` accepts OSM name variants (comma separated); the script picks the
  relation with the most geometry points.
- `--source` / `--mouth` are `lon,lat` hints used to orient the path; refine
  them if the path looks wrong.
- (Optional) For convenience you can instead add the river to `RIVER_CONFIGS` in
  `fetch_river.py` and call `python fetch_river.py --key inn --out inn.json`.

Schema written to `<key>.json`:

```json
{ "source":[lon,lat], "mouth":[lon,lat], "length_km":<int>,
  "elev_min":<m>, "elev_max":<m>,
  "ways":[[ [lon,lat,elev,abfall], ... ], ...] }
```

If you want a smoother path, optionally run `smooth_river.py` on the result
before contours (not required).

---

## 5. Step 3 — Contours → `<key>_contours.json`

`contour.py` reads `dem/*.tif`, builds a river buffer, and writes isolines:

```powershell
python contour.py inn.json   100 500 3000 --out inn_contours.json
python contour.py saone.json 100 500 3000 --out saone_contours.json
python contour.py doubs.json 100 500 3000 --out doubs_contours.json
python contour.py donau.json 100 500 3000 --out donau_contours.json
```

Arguments: `<file> <interval_m> <smooth_m> <buffer_m>` (interval 100 m,
smoothing 500 m, 3000 m buffer along the river). Output:

```json
{ "interval_m":100, "smooth_m":500, "buffer_m":3000,
  "levels":[ {"elev":<m>, "segments":[[ [lon,lat],[lon,lat] ], ...]}, ... ] }
```

---

## 6. Step 4 — Cities → `river_cities.csv`

Append one row per city, **downstream order** (source → mouth). Columns:

```
river,name,pop,lon,lat,alt
```

Example rows (elevations from Open-Meteo, populations approximate):

```
inn,St. Moritz,4911,9.845,46.490,1821
inn,Innsbruck,132493,11.393,47.265,579
inn,Rosenheim,67300,12.127,47.857,450
inn,Passau,50800,13.469,48.574,315
saone,Dijon,156920,5.041,47.322,250
saone,Chalon-sur-Saône,45300,4.896,46.786,178
saone,Mâcon,33900,4.828,46.306,196
saone,Lyon,513000,4.835,45.757,178
doubs,St. Ursanne,700,7.135,47.354,643
doubs,Audincourt,14300,6.861,47.484,343
doubs,Besançon,117100,6.032,47.238,250
donau,Donaueschingen,22100,8.134,47.953,1008
donau,Ulm,126290,9.983,48.399,479
donau,Regensburg,150000,12.101,49.020,327
donau,Passau,50800,13.469,48.574,315
donau,Linz,200000,14.305,48.306,264
donau,Wien,1900000,16.373,48.208,192
donau,Budapest,1750000,19.040,47.498,113
```

The app reads `river_cities.csv` once at startup and filters by `river == <key>`.

---

## 7. Step 5 (later) — Register the river in the app

The river list is read from `conf.yaml` at startup (not hardcoded in `main.js`):

1. **`conf.yaml` → `rivers`** add an entry (the `<key>_contours.json` name is
   derived automatically; for Rhein it is the special `river_contours.json`):

   ```yaml
   - key: inn
     label: Inn
   - key: saone
     label: Saône
   - key: doubs
     label: Doubs
   - key: donau
     label: Donau
   ```

2. **`conf.yaml` → `cities`** add the city heights & populations for the new river
   (the CSV only stores `river,name,lon,lat,mouth`):

   ```yaml
   inn:
     "St. Moritz": { altitude: 1821, people: 4911 }
     Innsbruck:    { altitude: 579,  people: 132493 }
     Rosenheim:    { altitude: 450,  people: 67300 }
     Passau:       { altitude: 315,  people: 50800 }
   ```

3. (Optional) **`fetch_river.py` → `RIVER_CONFIGS`** add the same keys so you can
   re-run with `--key inn` instead of the long `--names/--source/--mouth` form.

After that, the river appears in the selector and the map/cities/contours load
automatically.

> Note: the map uses a fixed `GBOX` (lon 3.5–13.5, lat 43–52.5). Rivers or
> cities outside that box (e.g. Wien, Budapest) will be generated fine but
> render outside the current visible area until `GBOX` is widened.

---

## 8. Sources used

All data comes from the sources already listed in `sources.txt`:

1. **FABDEM** — elevation model (fabdem-v12, University of Bristol).
   Mirror: `https://huggingface.co/datasets/pavelzaitsau/fabdem-v12/resolve/main/tiles`
   License: free for research / non-commercial; commercial use needs a license
   from Bristol. Attribution: "FABDEM (c) University of Bristol".
2. **OpenStreetMap (Overpass API)** — river geometry.
   `https://overpass-api.de/api/interpreter` (fallback `overpass.kumi.systems`).
   License: ODbL — attribution "© OpenStreetMap contributors" required; share-alike
   on derived databases.
3. **Open-Meteo Elevation API** — fallback point elevations.
   `https://api.open-meteo.com/v1/elevation` — free, attribution appreciated.
4. **Natural Earth** — country borders (used by `build_countries.py` / legend),
   public domain. `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/`
5. **three.js** — 3D rendering (via CDN), MIT license.

When publishing, verify the individual licenses (especially FABDEM commercial
use and OSM ODbL share-alike) — see `sources.txt` for the full legal notes.
