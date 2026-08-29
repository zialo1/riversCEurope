"""Baut rhein.json aus OpenStreetMap (Overpass) mit FABDEM-/Open-Meteo-Hoehen.

Holt die Rhein-Relation, verknuepft ihre Wege zum langsten Flusspfad von
Quelle bis Muendung und versieht ihn mit Hoehe (m) und Abfallrate (m/km).
"""

import json
import math
import os
import sys
import glob
import time
import urllib.parse
import urllib.request
import heapq

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

NAMES = ["Rhein", "Rhin", "Rhine", "Rijn"]


def query(data, timeout=180):
    body = urllib.parse.urlencode({"data": data}).encode()
    import time
    last_err = None
    for attempt in range(4):
        for url in ENDPOINTS:
            try:
                req = urllib.request.Request(
                    url, data=body, headers={"User-Agent": "rhein-fetch/1.0"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except Exception as e:
                last_err = e
        print(f"  Versuch {attempt+1} fehlgeschlagen: {last_err}; warte ...", file=sys.stderr)
        time.sleep(5 * (attempt + 1))
    raise last_err


def dist_deg(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def seg_len(a, b):
    dx = (a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2)) * 111.32
    dy = (a[1] - b[1]) * 110.57
    return math.hypot(dx, dy)


# 1) Kandidaten-Relationen sammeln
name_re = "^(" + "|".join(NAMES) + ")$"
q = f'[out:json][timeout:120];relation["waterway"="river"]["name"~"{name_re}"];out tags;'
print("Suche Relationen ...", file=sys.stderr)
rels = query(q).get("elements", [])
print(f"  {len(rels)} Relation(en) gefunden", file=sys.stderr)
for r in rels:
    print("   ", r["id"], r.get("tags", {}).get("name"), file=sys.stderr)

# 2) Geometrie der laengsten Relation holen
best = None
for r in rels:
    rid = r["id"]
    qg = f"[out:json][timeout:180];rel({rid});way(r);out geom;"
    try:
        data = query(qg)
    except Exception as e:
        print("  Fehler bei", rid, e, file=sys.stderr)
        continue
    ways = [e for e in data["elements"] if e["type"] == "way" and "geometry" in e]
    pts_total = sum(len(w["geometry"]) for w in ways)
    print(f"  rel {rid}: {len(ways)} ways, {pts_total} punkte", file=sys.stderr)
    if best is None or pts_total > best["pts"]:
        best = {"rid": rid, "ways": ways, "pts": pts_total}

if best is None:
    print("Keine Relation mit Geometrie gefunden.", file=sys.stderr)
    sys.exit(1)
print(f"Waehle Relation {best['rid']} mit {best['pts']} Punkten", file=sys.stderr)

polys = [[(p["lon"], p["lat"]) for p in w["geometry"]] for w in best["ways"]]

# 3) Graphen aus Wegen aufbauen
coords = {}

def nid(lon, lat):
    k = (round(lon, 5), round(lat, 5))
    if k not in coords:
        coords[k] = (lon, lat)
    return k

edges = []
for poly in polys:
    a = nid(*poly[0])
    b = nid(*poly[-1])
    w = sum(seg_len(poly[i - 1], poly[i]) for i in range(1, len(poly)))
    edges.append((a, b, poly, w))

parent = {k: k for k in coords}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
def union(x, y):
    rx, ry = find(x), find(y)
    if rx != ry:
        parent[rx] = ry

for a, b, _, _ in edges:
    union(a, b)

comp = {}
for k in coords:
    comp.setdefault(find(k), []).append(k)

SOURCE = (8.67, 46.66)
MOUTH = (4.15, 51.95)
source_key = min(coords, key=lambda k: dist_deg(coords[k], SOURCE))
mouth_key = min(coords, key=lambda k: dist_deg(coords[k], MOUTH))

connected = {find(source_key)}
remaining = set(comp.keys()) - connected
bridges = []
while remaining:
    best_pair = None
    best_d = 1e9
    for cr in connected:
        for ck in remaining:
            for ku in comp[cr]:
                for kv in comp[ck]:
                    d = dist_deg(coords[ku], coords[kv])
                    if d < best_d:
                        best_d, best_pair = d, (ku, kv, ck)
    if best_pair is None:
        break
    u, v, ck = best_pair
    bridges.append((u, v, best_d))
    union(u, v)
    connected.add(ck)
    remaining.discard(ck)
print(f"  {len(comp)} Komponenten, {len(bridges)} Bruecken", file=sys.stderr)

graph = {}
def add_edge(u, v, w):
    graph.setdefault(u, []).append((v, w))
    graph.setdefault(v, []).append((u, w))
for a, b, _, w in edges:
    add_edge(a, b, w)
for u, v, w in bridges:
    add_edge(u, v, w)

dist = {source_key: 0.0}
pq = [(0.0, source_key)]
while pq:
    d, u = heapq.heappop(pq)
    if d > dist.get(u, 1e18):
        continue
    for v, w in graph.get(u, []):
        nd = d + w
        if nd < dist.get(v, 1e18):
            dist[v] = nd
            heapq.heappush(pq, (nd, v))

d_mouth = dist.get(mouth_key, max(dist.values()))
print(f"  Pfadlaenge Quelle->Muendung ~{d_mouth:.0f} km", file=sys.stderr)


# 4) Hoehenquelle: FABDEM (lokale GeoTIFFs in dem/) falls vorhanden,
#    sonst echtes DEM ueber Open-Meteo, sonst linearer Fallback.
DEM_DIR = "dem"
dem_sources = []
try:
    import rasterio
    for t in sorted(glob.glob(os.path.join(DEM_DIR, "*.tif"))):
        dem_sources.append(rasterio.open(t))
        print(f"  FABDEM-Tile geladen: {t}", file=sys.stderr)
except ImportError:
    pass
except Exception as e:
    print(f"  rasterio-Fehler: {e}", file=sys.stderr)

_band_cache = {}
def sample_dem(lon, lat):
    for ds in dem_sources:
        if ds.bounds.left <= lon <= ds.bounds.right and ds.bounds.bottom <= lat <= ds.bounds.top:
            try:
                arr = _band_cache.get(id(ds))
                if arr is None:
                    arr = ds.read(1)
                    _band_cache[id(ds)] = arr
                row, col = ds.index(lon, lat)
                if 0 <= row < ds.height and 0 <= col < ds.width:
                    val = arr[row, col]
                    if ds.nodata is not None and val == ds.nodata:
                        return None
                    return float(val)
            except Exception:
                return None
    return None

def graph_elev(key):
    return 2000.0 * (1.0 - dist.get(key, 0.0) / d_mouth)

# Open-Meteo (echtes DEM) als praktische Hoehenquelle, wenn keine FABDEM-Tiles da sind
om_cache = {}
if not dem_sources:
    print("  Keine FABDEM-Tiles -> lade echte Hoehen ueber Open-Meteo ...", file=sys.stderr)
    allpts = []
    for a, b, poly, _ in edges:
        for (lon, lat) in poly:
            allpts.append((lon, lat))
    uniq = {}
    for lon, lat in allpts:
        uniq[(round(lon, 5), round(lat, 5))] = (lon, lat)
    items = list(uniq.values())
    batch = 100
    done = 0
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        lats = ",".join(str(lat) for _, lat in chunk)
        lons = ",".join(str(lon) for lon, _ in chunk)
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"
        res = None
        for attempt in range(8):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "rhein-fetch/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    res = json.loads(r.read())["elevation"]
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(2 * (attempt + 1))
                else:
                    time.sleep(1)
            except Exception:
                time.sleep(1)
        if res is None:
            print("    Open-Meteo Batch fehlgeschlagen -> linearer Fallback", file=sys.stderr)
            continue
        for (lon, lat), e in zip(chunk, res):
            om_cache[(round(lon, 5), round(lat, 5))] = float(e)
        done += len(chunk)
        time.sleep(0.25)  # zwischen Batches drosseln
    print(f"  {done} Punkte mit echten Hoehen geladen", file=sys.stderr)

def elev_at(lon, lat):
    e = sample_dem(lon, lat)
    if e is not None:
        return e
    key = (round(lon, 5), round(lat, 5))
    if key in om_cache:
        return om_cache[key]
    return None  # -> linearer Fallback im Aufrufer

# 5) Wege mit FABDEM-Hoehe und Abfallrate ausgeben
ways_out = []
elev_min, elev_max = 1e9, -1e9
for a, b, poly, _ in edges:
    n = len(poly)
    e_a = elev_at(*poly[0])
    e_a = e_a if e_a is not None else graph_elev(a)
    e_b = elev_at(*poly[-1])
    e_b = e_b if e_b is not None else graph_elev(b)
    elevs = []
    for i, (lon, lat) in enumerate(poly):
        e = elev_at(lon, lat)
        if e is None:
            f = i / (n - 1) if n > 1 else 0.0
            e = e_a + (e_b - e_a) * f
        elevs.append(e)
        if e < elev_min: elev_min = e
        if e > elev_max: elev_max = e
    # Abfallrate (m pro km) zwischen aufeinanderfolgenden Punkten
    rates = []
    for j in range(1, n):
        seg = seg_len(poly[j - 1], poly[j])
        rates.append((elevs[j - 1] - elevs[j]) / seg if seg > 0 else 0.0)
    desc = [0.0] * n
    for k in range(n):
        if n == 1:
            desc[k] = 0.0
        elif k == 0:
            desc[k] = rates[0]
        elif k == n - 1:
            desc[k] = rates[-1]
        else:
            desc[k] = (rates[k - 1] + rates[k]) / 2.0
    w = []
    for i, (lon, lat) in enumerate(poly):
        w.append([round(lon, 6), round(lat, 6), round(elevs[i], 1), round(desc[i], 2)])
    ways_out.append(w)

out = {
    "source": [round(coords[source_key][0], 5), round(coords[source_key][1], 5)],
    "mouth": [round(coords[mouth_key][0], 5), round(coords[mouth_key][1], 5)],
    "length_km": round(d_mouth),
    "elev_min": round(elev_min, 1),
    "elev_max": round(elev_max, 1),
    "ways": ways_out,
}

with open("rhein.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)

npts = sum(len(w) for w in ways_out)
print(f"rhein.json geschrieben: {len(ways_out)} Wege, {npts} Punkte", file=sys.stderr)
print(f"  Hoehenbereich: {elev_min:.0f} .. {elev_max:.0f} m "
      f"(Quelle ~({coords[source_key][0]:.3f},{coords[source_key][1]:.3f}) "
      f"Muendung ~({coords[mouth_key][0]:.3f},{coords[mouth_key][1]:.3f}))", file=sys.stderr)
if not dem_sources:
    print("  HINWEIS: Keine FABDEM-Tiles in dem/ gefunden -> lineare Ersatzhöhe verwendet.",
          file=sys.stderr)
