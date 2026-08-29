"""Laedt die benoetigten 1-Grad-FABDEM-Tiles (Hugging Face) nach dem/.

Nur die Kacheln im Rhein-Korridor werden heruntergeladen.
"""

import json, math, os, sys, time
import urllib.request
import urllib.error

REPO = "pavelzaitsau/fabdem-v12"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/main/tiles"
DEM_DIR = "dem"
os.makedirs(DEM_DIR, exist_ok=True)


def collect_coords():
    pts = []
    if os.path.exists("rhein.json"):
        with open("rhein.json", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and "ways" in d:
            for w in d["ways"]:
                for c in w:
                    pts.append((c[0], c[1]))
        elif isinstance(d, list):
            for c in d:
                if isinstance(c, list) and len(c) >= 2:
                    pts.append((c[0], c[1]))
    return pts


def tile_url(latb, lonb):
    lat0 = (latb // 10) * 10
    lon0 = (lonb // 10) * 10
    folder = f"N{lat0:02d}E{lon0:03d}-N{lat0+10:02d}E{lon0+10:03d}_FABDEM_V1-2"
    fname = f"N{latb:02d}E{lonb:03d}_FABDEM_V1-2.tif"
    return f"{BASE}/{folder}/{fname}"


tiles = set()
for lon, lat in collect_coords():
    tiles.add((int(math.floor(lat)), int(math.floor(lon))))
# Sicherheits-Bounding-Box des Rheins
for latb in range(46, 53):
    for lonb in range(3, 11):
        tiles.add((latb, lonb))

print(f"  {len(tiles)} 1-Grad-FABDEM-Tiles werden geladen", file=sys.stderr)

ok = 0
for (latb, lonb) in sorted(tiles):
    out = os.path.join(DEM_DIR, f"N{latb:02d}E{lonb:03d}_FABDEM_V1-2.tif")
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        ok += 1
        continue
    url = tile_url(latb, lonb)
    done = False
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fabdem-dl/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r, open(out, "wb") as w:
                w.write(r.read())
            sz = os.path.getsize(out)
            if sz > 1000:
                ok += 1
                print(f"  ok N{latb:02d}E{lonb:03d} ({sz} bytes)", file=sys.stderr)
                done = True
                break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (attempt + 1))
            else:
                print(f"  HTTP {e.code} {url}", file=sys.stderr)
                break
        except Exception as e:
            print(f"  Fehler {url}: {e}", file=sys.stderr)
            time.sleep(2)
    if not done:
        print(f"  UEBERSPRUNGEN N{latb:02d}E{lonb:03d}", file=sys.stderr)

print(f"  {ok}/{len(tiles)} FABDEM-Tiles vorhanden", file=sys.stderr)
