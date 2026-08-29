"""Laedt Laendergrenzen, Seen und Staedte (Natural Earth) fuer den Rhein-Korridor.

Ergebnis: geo.json mit den Schluesseln countries, lakes, cities.
"""

import json
import sys
import urllib.request

URLS = {
    "countries": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_boundary_lines_land.geojson",
    "lakes": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_lakes.geojson",
    "cities": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places.geojson",
}

# Rechteck um den Rhein-Korridor (mit Rand)
BBOX = (3.8, 46.3, 10.2, 52.8)  # minlon, minlat, maxlon, maxlat
MIN_POP = 50000  # nur "grosse" Staedte als Kandidaten


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


def extract_lines(geom):
    t = geom["type"]
    if t == "LineString":
        return [geom["coordinates"]]
    if t == "MultiLineString":
        return list(geom["coordinates"])
    if t == "Polygon":
        return list(geom["coordinates"])
    if t == "MultiPolygon":
        return [ring for poly in geom["coordinates"] for ring in poly]
    return []


def extract_polygons(geom):
    t = geom["type"]
    if t == "Polygon":
        return [geom["coordinates"]]
    if t == "MultiPolygon":
        return list(geom["coordinates"])
    return []


out = {"countries": [], "lakes": [], "cities": []}

print("Lade Laender...", file=sys.stderr)
for feat in download(URLS["countries"])["features"]:
    geom = feat.get("geometry")
    if geom and geom_in_bbox(geom):
        for line in extract_lines(geom):
            out["countries"].append([[round(x, 5), round(y, 5)] for x, y in line])

print("Lade Seen...", file=sys.stderr)
for feat in download(URLS["lakes"])["features"]:
    geom = feat.get("geometry")
    if geom and geom_in_bbox(geom):
        name = feat.get("properties", {}).get("NAME") or feat.get("properties", {}).get("name") or ""
        for poly in extract_polygons(geom):
            out["lakes"].append({
                "name": name,
                "rings": [[[round(x, 5), round(y, 5)] for x, y in ring] for ring in poly],
            })

print("Lade Staedte...", file=sys.stderr)
for feat in download(URLS["cities"])["features"]:
    geom = feat.get("geometry")
    if not geom or geom["type"] != "Point":
        continue
    lon, lat = geom["coordinates"]
    if not in_bbox(lon, lat):
        continue
    p = feat.get("properties", {})
    pop = p.get("POP_MIN") or p.get("POP_MAX") or 0
    if pop < MIN_POP:
        continue
    name = p.get("NAME") or p.get("name") or ""
    out["cities"].append(
        {"name": name, "lon": round(lon, 5), "lat": round(lat, 5), "pop": int(pop)}
    )

with open("geo.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)

print(
    f"geo.json geschrieben: {len(out['countries'])} Grenzlinien, "
    f"{len(out['lakes'])} Seen, {len(out['cities'])} Staedte",
    file=sys.stderr,
)
