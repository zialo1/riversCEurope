"""Erzeugt countries.json: Laendergrenzen (Natural Earth) + Hauptstaedte.

Nur Laender innerhalb des Rhein-Korridors; Hauptstadt-Koordinaten sind
fest hinterlegt.
"""

import json
import sys
import urllib.request

BBOX = (3.8, 46.3, 10.2, 52.8)  # minlon, minlat, maxlon, maxlat (Rhein-Korridor)

CAPITALS = {
    "Switzerland": ("Bern", 7.4474, 46.9480),
    "France": ("Paris", 2.3522, 48.8566),
    "Germany": ("Berlin", 13.4050, 52.5200),
    "Netherlands": ("Amsterdam", 4.9041, 52.3676),
    "Belgium": ("Brussels", 4.3488, 50.8503),
    "Luxembourg": ("Luxembourg", 6.1296, 49.6116),
    "Austria": ("Vienna", 16.3738, 48.2082),
    "Liechtenstein": ("Vaduz", 9.5554, 47.1625),
    "Italy": ("Rome", 12.4964, 41.9028),
}

URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "geo-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def in_bbox(lon, lat):
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def coords_iter(geom):
    t = geom["type"]
    if t == "Point":
        yield geom["coordinates"]
    elif t in ("LineString", "MultiPoint"):
        for c in geom["coordinates"]:
            yield c
    elif t in ("MultiLineString", "Polygon"):
        for part in geom["coordinates"]:
            for c in part:
                yield c
    elif t == "MultiPolygon":
        for poly in geom["coordinates"]:
            for part in poly:
                for c in part:
                    yield c


def geom_in_bbox(geom):
    return any(in_bbox(lon, lat) for lon, lat in coords_iter(geom))


def exterior_rings(geom):
    """Aeussere Ringe je Polygon als Linestrings (Grenzen ohne Binnenseen)."""
    t = geom["type"]
    rings = []
    if t == "Polygon":
        rings.append(geom["coordinates"][0])
    elif t == "MultiPolygon":
        for poly in geom["coordinates"]:
            rings.append(poly[0])
    return rings


out = {"countries": []}
for feat in download(URL)["features"]:
    geom = feat.get("geometry")
    if not geom or not geom_in_bbox(geom):
        continue
    p = feat.get("properties", {})
    name = p.get("NAME") or p.get("ADMIN") or p.get("name") or ""
    cap = None
    if name in CAPITALS:
        cn, clon, clat = CAPITALS[name]
        cap = {"name": cn, "lon": round(clon, 5), "lat": round(clat, 5)}
    borders = [
        [[round(x, 5), round(y, 5)] for x, y in ring]
        for ring in exterior_rings(geom)
        if len(ring) >= 2
    ]
    out["countries"].append({"name": name, "capital": cap, "borders": borders})

with open("countries.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)

print(f"countries.json: {len(out['countries'])} Laender", file=sys.stderr)
for c in out["countries"]:
    cap = c["capital"]
    print(f"  - {c['name']}: {len(c['borders'])} Grenzlinien, Hauptstadt={cap['name'] if cap else '-'}",
          file=sys.stderr)
