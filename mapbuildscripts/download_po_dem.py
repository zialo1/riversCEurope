import os, urllib.request, time
REPO = "pavelzaitsau/fabdem-v12"
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/main/tiles"
DEM_DIR = "dem"
os.makedirs(DEM_DIR, exist_ok=True)

def tile_url(latb, lonb):
    lat0 = (latb // 10) * 10
    lon0 = (lonb // 10) * 10
    folder = f"N{lat0:02d}E{lon0:03d}-N{lat0+10:02d}E{lon0+10:03d}_FABDEM_V1-2"
    fname = f"N{latb:02d}E{lonb:03d}_FABDEM_V1-2.tif"
    return f"{BASE}/{folder}/{fname}"

tiles = set()
for latb in (44, 45):
    for lonb in range(6, 14):
        tiles.add((latb, lonb))
print(f"lade {len(tiles)} Tiles")
ok = 0
for (latb, lonb) in sorted(tiles):
    out = os.path.join(DEM_DIR, f"N{latb:02d}E{lonb:03d}_FABDEM_V1-2.tif")
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        ok += 1; continue
    url = tile_url(latb, lonb)
    done = False
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fabdem-dl/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r, open(out, "wb") as w:
                w.write(r.read())
            if os.path.getsize(out) > 1000:
                ok += 1; print(f"  ok N{latb:02d}E{lonb:03d}"); done = True; break
        except Exception as e:
            time.sleep(2)
    if not done:
        print(f"  UEBERSPRUNGEN N{latb:02d}E{lonb:03d}")
print(f"{ok}/{len(tiles)} vorhanden")
