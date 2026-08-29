"""Erzeugt river_plus.json: Seen (aus geo.json) + verbundenes Meer (Nordsee).

Die Nordsee wird aus Natural Earth Marina-Polygonen auf den Korridor
zugeschnitten.
"""

import json
import sys
import urllib.request

BBOX = (3.8, 46.3, 10.2, 52.8)  # minlon, minlat, maxlon, maxlat
MARINE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_geography_marine_polys.geojson"


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "geo-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def clip_ring(ring, xmin, ymin, xmax, ymax):
    """Sutherland-Hodgman: schneidet ein Ring-Polygon auf das BBOX-Rechteck."""
    def inside(p, edge):
        return (edge == 0 and p[0] >= xmin) or (edge == 1 and p[1] >= ymin) or \
               (edge == 2 and p[0] <= xmax) or (edge == 3 and p[1] <= ymax)

    def intersect(p, q, edge):
        if edge == 0:  # x = xmin
            t = (xmin - p[0]) / (q[0] - p[0])
        elif edge == 1:  # y = ymin
            t = (ymin - p[1]) / (q[1] - p[1])
        elif edge == 2:  # x = xmax
            t = (xmax - p[0]) / (q[0] - p[0])
        else:  # y = ymax
            t = (ymax - p[1]) / (q[1] - p[1])
        return [p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]

    out = list(ring)
    for edge in range(4):
        if not out:
            break
        inp = out
        out = []
        prev = inp[-1]
        for cur in inp:
            if inside(cur, edge):
                if not inside(prev, edge):
                    out.append(intersect(prev, cur, edge))
                out.append(cur)
            elif inside(prev, edge):
                out.append(intersect(prev, cur, edge))
            prev = cur
    return out


def clip_polygon(rings):
    """rings[0]=aussen, rest=loecher. Schneidet alles auf BBOX; loecher ausserhalb weg."""
    outer = clip_ring(rings[0], *BBOX)
    if len(outer) < 3:
        return None
    holes = []
    for h in rings[1:]:
        ch = clip_ring(h, *BBOX)
        if len(ch) >= 3:
            holes.append(ch)
    return [[[round(x, 5), round(y, 5)] for x, y in outer]] + \
           [[[round(x, 5), round(y, 5)] for x, y in hole] for hole in holes]


def polys_of(geom):
    t = geom["type"]
    if t == "Polygon":
        return [geom["coordinates"]]
    if t == "MultiPolygon":
        return list(geom["coordinates"])
    return []


# --- Seen aus geo.json uebernehmen ---
with open("geo.json", encoding="utf-8") as f:
    geo = json.load(f)
lakes = geo.get("lakes", [])
print(f"Seen aus geo.json: {len(lakes)}", file=sys.stderr)

# --- Verbundenes Meer: Nordsee (einzige, die der Rhein erreicht) ---
sea = None
for feat in download(MARINE_URL)["features"]:
    name = (feat.get("properties", {}) or {}).get("name") or \
           (feat.get("properties", {}) or {}).get("NAME") or ""
    if "north sea" in name.lower():
        for poly in polys_of(feat["geometry"]):
            clipped = clip_polygon(poly)
            if clipped:
                sea = {"name": "North Sea", "rings": clipped}
                break
    if sea:
        break

if not sea:
    print("  WARN: Nordsee nicht gefunden", file=sys.stderr)
else:
    n = len(sea["rings"][0])
    print(f"  Nordsee (BBOX-geclippt): {n} Aussenpunkte", file=sys.stderr)

out = {"lakes": lakes, "sea": sea}
with open("river_plus.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
print("river_plus.json geschrieben", file=sys.stderr)
