"""Baut <key>.json aus OpenStreetMap (Overpass) mit FABDEM-/Terrarium-Hoehen.

Generisch fuer beliebige Fluesse: Name(s), Quelle und Muendung werden als
Argumente uebergeben. Erzeugt eine Datei mit dem Schema von rhein.json:
  { source:[lon,lat], mouth:[lon,lat], length_km, elev_min, elev_max, ways:[[lon,lat,hoehe,abfall]] }
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
import argparse


# --- Terrarium (globale Hoehen ueber AWS; Luecken fuellen, keine Rate-Limits) ---
TERRA_DIR = "dem_terrarium"
_terra_cache = {}


def _terra_y_of_lat(lat, n):
    return (1 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n


def _terra_lat_of_y(y, n):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2.0 * y / n))))


def sample_terra(lon, lat, zoom=11):
    n = 2 ** zoom
    tx = int(math.floor((lon + 180.0) / 360.0 * n))
    ty = int(math.floor(_terra_y_of_lat(lat, n)))
    key = (zoom, tx, ty)
    if key not in _terra_cache:
        fn = os.path.join(TERRA_DIR, f"t{zoom}_{tx}_{ty}.png")
        ok = os.path.exists(fn) and os.path.getsize(fn) > 200
        if not ok:
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{tx}/{ty}.png"
            for attempt in range(5):
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "dem-dl/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        data = r.read()
                    os.makedirs(TERRA_DIR, exist_ok=True)
                    with open(fn, "wb") as f:
                        f.write(data)
                    ok = True
                    break
                except Exception:
                    time.sleep(2 * (attempt + 1))
        _terra_cache[key] = fn if ok else None
    fn = _terra_cache[key]
    if not fn:
        return None
    try:
        import PIL.Image
        lon_l = tx / n * 360.0 - 180.0
        lon_r = (tx + 1) / n * 360.0 - 180.0
        lat_t = _terra_lat_of_y(ty, n)
        lat_b = _terra_lat_of_y(ty + 1, n)
        fx = (lon - lon_l) / (lon_r - lon_l)
        fy = (lat_t - lat) / (lat_t - lat_b)
        px = int(min(255, max(0, fx * 256)))
        py = int(min(255, max(0, fy * 256)))
        with PIL.Image.open(fn) as im:
            r, g, b = im.getpixel((px, py))
        return float(r * 256.0 + g + b / 256.0 - 32768.0)
    except Exception:
        return None


ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]


def query(data, timeout=300):
    body = urllib.parse.urlencode({"data": data}).encode()
    last_err = None
    for attempt in range(6):
        for url in ENDPOINTS:
            try:
                req = urllib.request.Request(
                    url, data=body, headers={"User-Agent": "river-fetch/1.0"}
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


def run(names, source, mouth, out):
    name_re = "|".join(names)

    def search_relations(re):
        keys = ["name", "name:en", "name:fr", "name:de", "name:ru", "name:ro", "int_name", "alt_name"]
        found = []
        for kf in keys:
            q = f'[out:json][timeout:120];relation["waterway"="river"]["{kf}"~"{re}",i];out tags;'
            try:
                rels = query(q).get("elements", [])
            except Exception as e:
                print("  relation query fehlgeschlagen:", e, file=sys.stderr)
                rels = []
            if rels:
                print(f"  via {kf}: {len(rels)} Relation(en)", file=sys.stderr)
                found.extend(rels)
        seen = set()
        uniq = []
        for r in found:
            if r["id"] not in seen:
                seen.add(r["id"])
                uniq.append(r)
        return uniq

    print("Suche Relationen ...", file=sys.stderr)
    rels = search_relations(name_re)
    print(f"  {len(rels)} Relation(en) gefunden", file=sys.stderr)
    for r in rels:
        print("   ", r["id"], r.get("tags", {}).get("name"), file=sys.stderr)

    # nur exakte Namens-Treffer bevorzugen (vermeidet z.B. 'Loiret' bei 'Loire')
    variants_lower = set(v.lower() for v in names)
    def is_exact(r):
        for k, val in r.get("tags", {}).items():
            if k.startswith("name") and str(val).lower() in variants_lower:
                return True
        return False
    exact = [r for r in rels if is_exact(r)]
    if exact:
        print(f"  {len(exact)} exakte Namens-Treffer werden verwendet", file=sys.stderr)
        rels = exact

    best = None
    for r in rels:
        rid = r["id"]
        qg = f"[out:json][timeout:300];rel({rid});way(r);out geom;"
        try:
            data = query(qg, timeout=300)
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

    # Polyline auf ~250 m abstaendig resampling (OSM liefert extrem viele Stuetzpunkte)
    def resample_poly(poly, step_km=0.25):
        if len(poly) < 2:
            return [poly[0]]
        cum = [0.0]
        for i in range(1, len(poly)):
            cum.append(cum[-1] + seg_len(poly[i - 1], poly[i]))
        total = cum[-1]
        if total <= 1e-9:
            return [poly[0]]
        n = max(2, int(round(total / step_km)) + 1)
        out = []
        j = 1
        for k in range(n):
            d = total * k / (n - 1)
            while j < len(cum) and cum[j] < d:
                j += 1
            if j >= len(cum):
                j = len(cum) - 1
            d0 = cum[j - 1]; d1 = cum[j]
            f = 0.0 if d1 <= d0 else (d - d0) / (d1 - d0)
            a = poly[j - 1]; b = poly[j]
            out.append([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f])
        return out

    polys = [resample_poly(p) for p in polys]

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

    source_key = min(coords, key=lambda k: dist_deg(coords[k], source))
    mouth_key = min(coords, key=lambda k: dist_deg(coords[k], mouth))

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

    def add_edge(u, v, w, poly):
        graph.setdefault(u, []).append((v, w, poly))
        graph.setdefault(v, []).append((u, w, poly))

    for a, b, poly, w in edges:
        add_edge(a, b, w, poly)
    for u, v, w in bridges:
        add_edge(u, v, w, None)

    dist = {source_key: 0.0}
    prev = {}
    pq = [(0.0, source_key)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18):
            continue
        for v, w, poly in graph.get(u, []):
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = (u, poly)
                heapq.heappush(pq, (nd, v))

    # Nur das Hauptbett (Quelle->Muendung) behalten, Nebenfluesse wegfallen lassen
    main_polys = []
    cur = mouth_key
    while cur != source_key and cur in prev:
        u, poly = prev[cur]
        if poly is not None:
            if nid(*poly[0]) == u and nid(*poly[-1]) == cur:
                main_polys.append(poly)
            elif nid(*poly[-1]) == u and nid(*poly[0]) == cur:
                main_polys.append(list(reversed(poly)))
            else:
                main_polys.append(poly)
        cur = u
    main_polys.reverse()
    if not main_polys or cur != source_key:
        main_polys = [poly for (a, b, poly, w) in edges]  # Fallback: alle Wege
    print(f"  Hauptbett: {len(main_polys)} Wege, "
          f"{sum(len(p) for p in main_polys)} Punkte", file=sys.stderr)

    d_mouth = dist.get(mouth_key, max(dist.values()))
    print(f"  Pfadlaenge Quelle->Muendung ~{d_mouth:.0f} km", file=sys.stderr)

    # Hoehen
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
        return 2500.0 * (1.0 - dist.get(key, 0.0) / d_mouth)

    def elev_at(lon, lat):
        e = sample_dem(lon, lat)
        if e is not None:
            return e
        return sample_terra(lon, lat)

    ways_out = []
    elev_min, elev_max = 1e9, -1e9

    # --- Roh-Hoehen aller Punkte sammeln + fliessabwaerts-Distanz je Punkt ---
    TOL = 40.0       # m: erlaubtes Rauschen zwischen aufeinanderfolgenden Punkten
    FLOOR = -5.0      # m: darunter als Messfehler werten
    DESCENT = 2.0     # m/km: Abfall fuer Extrapolation am Flussende
    raw_pts = []      # (pdist, key, lon, lat, raw)
    for poly in main_polys:
        da = dist.get((round(poly[0][0], 5), round(poly[0][1], 5)), 0.0)
        db = dist.get((round(poly[-1][0], 5), round(poly[-1][1], 5)), 0.0)
        cum = [0.0]
        for i in range(1, len(poly)):
            cum.append(cum[-1] + seg_len(poly[i - 1], poly[i]))
        tot = cum[-1] if cum[-1] > 1e-9 else 1.0
        for i, (lon, lat) in enumerate(poly):
            pdist = da + (db - da) * (cum[i] / tot)
            raw_pts.append([pdist, (round(lon, 5), round(lat, 5)), lon, lat, elev_at(lon, lat)])
    raw_pts.sort(key=lambda p: p[0])

    # --- Zuverlaessigkeitspass: flussabwaerts darf nicht hoeher sein ---
    final = {}
    last_rel = None
    n_unreliable = 0
    for p in raw_pts:
        pdist, key, lon, lat, raw = p
        if raw is not None and raw > FLOOR and (last_rel is None or raw <= last_rel + TOL):
            last_rel = raw
            p.append(True)    # zuverlaessig
            final[key] = raw
        else:
            p.append(False)   # unzuverlaessig
            n_unreliable += 1
            if raw is None:
                print("  WARN Hoehe fehlt bei (%s, %s)" % (lon, lat), file=sys.stderr)
            else:
                print("  WARN unzuverlaessige Hoehe %g m bei (%s, %s): flussabwaerts hoeher "
                      "als letzte zuverlaessige %g m" % (raw, lon, lat,
                      last_rel if last_rel is not None else float('nan')), file=sys.stderr)

    # --- Ersatz aus zuverlaessigen Nachbarn (Interpolation / Abfall) ---
    rel_list = [(p[0], final[p[1]]) for p in raw_pts if p[5]]
    for p in raw_pts:
        pdist, key, lon, lat, raw, ok = p
        if ok:
            continue
        prev = None
        nxt = None
        for d, e in rel_list:
            if d <= pdist and (prev is None or d > prev[0]):
                prev = (d, e)
            if d >= pdist and (nxt is None or d < nxt[0]):
                nxt = (d, e)
        if prev is not None and nxt is not None:
            frac = (pdist - prev[0]) / (nxt[0] - prev[0]) if nxt[0] > prev[0] else 0.0
            val = prev[1] + (nxt[1] - prev[1]) * frac
        elif nxt is not None:
            val = nxt[1]
        elif prev is not None:
            val = max(0.0, prev[1] - DESCENT * (pdist - prev[0]) / 1000.0)
        else:
            val = graph_elev(key)
        final[key] = val
    if n_unreliable:
        print("  %d unzuverlaessige Hoehen ersetzt (flussabwaerts hoeher als Vorgaenger "
              "oder fehlend)" % n_unreliable, file=sys.stderr)

    # --- Wege mit korrigierten Hoehen aufbauen ---
    for poly in main_polys:
        n = len(poly)
        elevs = []
        for (lon, lat) in poly:
            k = (round(lon, 5), round(lat, 5))
            e = final.get(k)
            if e is None:
                e = graph_elev(k)
            elevs.append(e)
            if e < elev_min: elev_min = e
            if e > elev_max: elev_max = e
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

    outd = {
        "source": [round(coords[source_key][0], 5), round(coords[source_key][1], 5)],
        "mouth": [round(coords[mouth_key][0], 5), round(coords[mouth_key][1], 5)],
        "length_km": round(d_mouth),
        "elev_min": round(elev_min, 1),
        "elev_max": round(elev_max, 1),
        "ways": ways_out,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(outd, f, ensure_ascii=False)
    npts = sum(len(w) for w in ways_out)
    print(f"{out} geschrieben: {len(ways_out)} Wege, {npts} Punkte, "
          f"Hoehen {elev_min:.0f}..{elev_max:.0f} m", file=sys.stderr)


# Vordefinierte Fluesse (vermeidet Shell-Encoding-Probleme mit Umlauten/Akzenten)
RIVER_CONFIGS = {
    "rhone":  {"names": ["Le Rhône", "Rhône", "Rhone"], "source": [8.33, 46.46], "mouth": [4.85, 43.33]},
    "aare":   {"names": ["Aare", "Aar"],            "source": [8.38, 46.55], "mouth": [7.59, 47.57]},
    "reuss":  {"names": ["Reuss", "Reuß"],          "source": [8.57, 46.59], "mouth": [8.208, 47.482]},
    "ticino": {"names": ["Ticino"],                 "source": [8.56, 46.53], "mouth": [9.25, 45.00]},
    "po":     {"names": ["Fiume Po", "Po"],         "source": [7.07, 44.97], "mouth": [12.40, 44.90]},
    "inn":    {"names": ["Inn"],                    "source": [9.842, 46.498], "mouth": [13.47, 48.57]},
    "saone":  {"names": ["La Saône", "Saône", "Saone"], "source": [4.93, 47.30], "mouth": [4.835, 45.764]},
    "doubs":  {"names": ["Le Doubs", "Doubs"],      "source": [6.20, 46.69], "mouth": [5.00, 46.84]},
    "donau":  {"names": ["Donau", "Danube"],        "source": [8.515, 47.953], "mouth": [29.66, 45.20]},
    "dnieper": {"names": ["Днепр", "Dnieper", "Dnipro"], "source": [33.50, 55.50], "mouth": [32.30, 46.50]},
    "dniester": {"names": ["Дністер", "Dniester", "Nistru"], "source": [25.30, 48.30], "mouth": [30.30, 46.40]},
    "elbe":   {"names": ["Elbe", "Labe", "Łaba"],   "source": [15.52, 50.78], "mouth": [8.73, 53.93]},
    "vistula": {"names": ["Wisła", "Vistula", "Weichsel"], "source": [19.50, 49.60], "mouth": [18.90, 54.00]},
    "oder":   {"names": ["Oder", "Odra"],           "source": [17.00, 50.30], "mouth": [14.30, 53.90]},
    "loire":  {"names": ["Loire", "La Loire"],      "source": [3.90, 44.90], "mouth": [-1.40, 45.55]},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", help="vordefinierter Fluss aus RIVER_CONFIGS")
    ap.add_argument("--names", help="OSM-Namensalternativen, Komma-getrennt")
    ap.add_argument("--source", help="Quelle lon,lat")
    ap.add_argument("--mouth", help="Muendung lon,lat")
    ap.add_argument("--out", required=True, help="Ausgabedatei")
    a = ap.parse_args()
    if a.key:
        cfg = RIVER_CONFIGS[a.key]
        names, source, mouth = cfg["names"], cfg["source"], cfg["mouth"]
    else:
        names = [x.strip() for x in a.names.split(",")]
        source = [float(x) for x in a.source.split(",")]
        mouth = [float(x) for x in a.mouth.split(",")]
    run(names, source, mouth, a.out)


if __name__ == "__main__":
    main()
