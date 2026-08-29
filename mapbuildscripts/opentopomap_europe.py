#!/usr/bin/env python3
"""Download OpenTopoMap tiles for a Europe bounding box and save as a georeferenced TIFF.

NOTE: OpenTopoMap's public raster tiles are served pre-rendered WITH labels.
There is no official no-labels raster endpoint; removing labels would require
self-rendering the map (see https://github.com/der-stefan/OpenTopoMap).

Dependencies:
    pip install requests pillow rasterio numpy

Usage:
    python opentopomap_europe.py                # default zoom 5
    python opentopomap_europe.py --zoom 6
"""

import argparse
import math
import os
import time

import numpy as np
import requests
from PIL import Image
import rasterio
from rasterio.transform import from_origin

TILE_SIZE = 256
SUBDOMAINS = ["a", "b", "c"]
TILE_URL = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"

# Rough bounding box of Europe (west, south, east, north) in WGS84.
EUROPE_BBOX = (-25.0, 34.0, 45.0, 72.0)

WORLD_MERC_EXTENT = 20037508.342789244  # half world width in EPSG:3857


def lon_lat_to_tile_fraction(lon, lat, zoom):
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def fetch_tile(z, x, y, session, timeout=30):
    url = TILE_URL.format(s=SUBDOMAINS[(x + y) % len(SUBDOMAINS)], z=z, x=x, y=y)
    for attempt in range(3):
        try:
            r = session.get(url, timeout=timeout, headers={"User-Agent": "opentopomap-tiff/1.0"})
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("RGB")
        except Exception:
            time.sleep(1 + attempt)
    raise RuntimeError(f"Failed to download tile {z}/{x}/{y}")


from io import BytesIO


def main():
    parser = argparse.ArgumentParser(description="Download OpenTopoMap of Europe as a TIFF.")
    parser.add_argument("--zoom", type=int, default=5, help="Tile zoom level (3-8 recommended).")
    parser.add_argument("--bbox", type=float, nargs=4, default=EUROPE_BBOX,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--out", default="europe_opentopomap.tif", help="Output TIFF path.")
    parser.add_argument("--delay", type=float, default=0.05, help="Delay between tile requests (s).")
    args = parser.parse_args()

    west, south, east, north = args.bbox
    z = args.zoom
    n = 2 ** z

    x0f, y_top = lon_lat_to_tile_fraction(west, north, z)     # top-left (north)
    x1f, y_bottom = lon_lat_to_tile_fraction(east, south, z)   # bottom-right (south)

    x0, x1 = int(math.floor(x0f)), int(math.ceil(x1f))
    y0, y1 = int(math.floor(y_top)), int(math.ceil(y_bottom))

    tiles_x = x1 - x0
    tiles_y = y1 - y0
    total = tiles_x * tiles_y
    print(f"Zoom {z}: {tiles_x} x {tiles_y} = {total} tiles")

    if total > 4000:
        print("WARNING: large number of tiles; this may take a long time and hit usage limits.")

    width = tiles_x * TILE_SIZE
    height = tiles_y * TILE_SIZE
    canvas = Image.new("RGB", (width, height))

    session = requests.Session()
    idx = 0
    for ty in range(y0, y1):
        for tx in range(x0, x1):
            tile = fetch_tile(z, tx, ty, session)
            canvas.paste(tile, ((tx - x0) * TILE_SIZE, (ty - y0) * TILE_SIZE))
            idx += 1
            if idx % 50 == 0:
                print(f"  downloaded {idx}/{total}")
            time.sleep(args.delay)

    # Georeference in EPSG:3857 (Web Mercator)
    pixel_size = (2 * WORLD_MERC_EXTENT) / (n * TILE_SIZE)
    # Top-left corner (x_min, y_max) in meters
    x_min = -WORLD_MERC_EXTENT + x0 * TILE_SIZE * pixel_size
    y_max = WORLD_MERC_EXTENT - y0 * TILE_SIZE * pixel_size
    transform = from_origin(x_min, y_max, pixel_size, pixel_size)

    arr = np.asarray(canvas).transpose(2, 0, 1).astype("uint8")  # (bands, H, W)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with rasterio.open(
        args.out, "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype="uint8",
        crs="EPSG:3857",
        transform=transform,
        photometric="RGB",
        compress="jpeg",
    ) as dst:
        dst.write(arr)

    print(f"Saved: {args.out} ({width} x {height} px, EPSG:3857)")


if __name__ == "__main__":
    main()
