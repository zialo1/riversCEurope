"""FABDEM-Hoehenlinien (Isolinien) des Rheins.

Liest FABDEM-GeoTIFFs (dem/), erzeugt geglaettete Hoehenlinien nur entlang
des Rheins und schreibt sie nach river_contours.json.
"""

import json
import math
import sys
import os
import glob
import time
import urllib.request
import argparse
import numpy as np
import rasterio


# ---------------------------------------------------------------------------
# Module-level algorithm helpers (stateless)
# ---------------------------------------------------------------------------
def dilate3x3(m):
    p = np.pad(m, 1)
    ny, nx = m.shape
    shifts = [p[dj:dj + ny, di:di + nx] for dj in (0, 1, 2) for di in (0, 1, 2)]
    return np.maximum.reduce(shifts)


def box_filter(img, r):
    if r <= 0:
        return img
    pad = np.pad(img, r, mode="edge").astype(np.float64)
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    ny, nx = img.shape
    c00 = c[0:ny, 0:nx]
    c01 = c[0:ny, 2 * r:2 * r + nx]
    c10 = c[2 * r:2 * r + ny, 0:nx]
    c11 = c[2 * r:2 * r + ny, 2 * r:2 * r + nx]
    s = c11 - c01 - c10 + c00
    return (s / ((2 * r + 1) ** 2)).astype(img.dtype)


def gaussian_approx(img, sigma):
    if sigma <= 0:
        return img
    r = max(1, int(round(sigma)))
    out = img.copy()
    for _ in range(3):
        out = box_filter(out, r)
    return out


def local_maxima(elev, covered):
    big = np.where(covered, elev, -np.inf)
    p = np.pad(big, 1, constant_values=-np.inf)
    ny, nx = elev.shape
    neigh = [
        p[1 + j:1 + j + ny, 1 + i:1 + i + nx]
        for j in (-1, 0, 1) for i in (-1, 0, 1)
        if not (i == 0 and j == 0)
    ]
    maxn = np.maximum.reduce(neigh)
    return (elev >= maxn) & covered


def build_river_mask(ways, x_min, y_min, step, nx, ny, mPerLon, mPerLat):
    mask = np.zeros((ny, nx), dtype=bool)
    for w in ways:
        for k in range(len(w)):
            lo0, la0 = w[k][0], w[k][1]
            x0, y0 = lo0 * mPerLon, la0 * mPerLat
            i0 = int(round((x0 - x_min) / step))
            j0 = int(round((y0 - y_min) / step))
            if 0 <= i0 < nx and 0 <= j0 < ny:
                mask[j0, i0] = True
            if k == 0:
                continue
            lo1, la1 = w[k - 1][0], w[k - 1][1]
            x1, y1 = lo1 * mPerLon, la1 * mPerLat
            n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / step)))
            for s in range(1, n + 1):
                t = s / n
                x = x0 + (x1 - x0) * t
                y = y0 + (y1 - y0) * t
                i = int(round((x - x_min) / step))
                j = int(round((y - y_min) / step))
                if 0 <= i < nx and 0 <= j < ny:
                    mask[j, i] = True
    return mask


def march_level(f, L, cells):
    segs = []
    for (j, i) in cells:
        if j >= f.shape[0] - 1 or i >= f.shape[1] - 1:
            continue
        a = f[j, i]; b = f[j, i + 1]; c = f[j + 1, i + 1]; d = f[j + 1, i]
        if np.isnan(a) or np.isnan(b) or np.isnan(c) or np.isnan(d):
            continue
        sa = a > L; sb = b > L; sc = c > L; sd = d > L
        if sa == sb == sc == sd:
            continue
        pts = []
        if sa != sb:
            t = (L - a) / (b - a); pts.append((i + t, j))
        if sb != sc:
            t = (L - b) / (c - b); pts.append((i + 1, j + t))
        if sd != sc:
            t = (L - d) / (c - d); pts.append((i + t, j + 1))
        if sa != sd:
            t = (L - a) / (d - a); pts.append((i, j + t))
        if len(pts) == 2:
            segs.append((pts[0], pts[1]))
        elif len(pts) == 4:
            segs.append((pts[0], pts[1]))
            segs.append((pts[2], pts[3]))
    return segs


# ---------------------------------------------------------------------------
# FABDEM tile access
# ---------------------------------------------------------------------------
class FabdemSampler:
    """Liest FABDEM-GeoTIFF-Kacheln und liefert ein Hoehenraster ueber den Korridor."""
    def __init__(self, dem_dir="dem"):
        self.tiles = sorted(glob.glob(os.path.join(dem_dir, "*.tif")))
        if not self.tiles:
            print("  FEHLER: keine FABDEM-Tiles in %s/ gefunden" % dem_dir, file=sys.stderr)
            sys.exit(1)

    def sample_grid(self, x_min, y_min, step, nx, ny, mPerLon, mPerLat):
        elev = np.full((ny, nx), np.nan, dtype=np.float32)
        for t in self.tiles:
            with rasterio.open(t) as ds:
                x0 = ds.bounds.left * mPerLon
                x1 = ds.bounds.right * mPerLon
                y0 = ds.bounds.bottom * mPerLat
                y1 = ds.bounds.top * mPerLat
                i0 = max(0, int(math.floor((x0 - x_min) / step)))
                i1 = min(nx - 1, int(math.ceil((x1 - x_min) / step)))
                j0 = max(0, int(math.floor((y0 - y_min) / step)))
                j1 = min(ny - 1, int(math.ceil((y1 - y_min) / step)))
                if i1 < i0 or j1 < j0:
                    continue
                xs = x_min + np.arange(i0, i1 + 1) * step
                ys = y_min + np.arange(j0, j1 + 1) * step
                Lons = xs / mPerLon
                Lats = ys / mPerLat
                Lon, Lat = np.meshgrid(Lons, Lats)
                t0 = ds.transform
                col = (Lon - t0.c) / t0.a
                row = (Lat - t0.f) / t0.e
                ic = np.rint(col).astype(int)
                ir = np.rint(row).astype(int)
                valid = (ic >= 0) & (ic <= ds.width - 1) & (ir >= 0) & (ir <= ds.height - 1)
                vals = ds.read(1)
                sampled = np.full(Lon.shape, np.nan)
                sampled[valid] = vals[ir[valid], ic[valid]]
                elev[j0:j1 + 1, i0:i1 + 1] = sampled
        return elev


# ---------------------------------------------------------------------------
# Globale Hoehen aus AWS "Terrarium"-Kacheln (SRTM-basiert, weltweit verfuegbar)
# ---------------------------------------------------------------------------
class TerrariumSampler:
    BASE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

    def __init__(self, cache_dir="dem_terrarium", zoom=None):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self.zoom = zoom

    def _fetch(self, z, x, y):
        fn = os.path.join(self.cache_dir, f"t{z}_{x}_{y}.png")
        if os.path.exists(fn) and os.path.getsize(fn) > 200:
            return fn
        url = self.BASE.format(z=z, x=x, y=y)
        last_err = None
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "dem-dl/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                with open(fn, "wb") as f:
                    f.write(data)
                return fn
            except Exception as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        print(f"  WARN Terrarium-Kachel {z}/{x}/{y} nicht ladbar: {last_err}", file=sys.stderr)
        return None

    @staticmethod
    def _y_of_lat(lat, n):
        return (1 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n

    @staticmethod
    def _lat_of_y(y, n):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2.0 * y / n))))

    def sample_grid(self, x_min, y_min, step, nx, ny, mPerLon, mPerLat):
        import PIL.Image
        lon0 = x_min / mPerLon
        lat0 = y_min / mPerLat
        lon1 = (x_min + nx * step) / mPerLon
        lat1 = (y_min + ny * step) / mPerLat
        lat_n = max(lat0, lat1)
        lat_s = min(lat0, lat1)
        if self.zoom is None:
            coslat = math.cos(math.radians((lat_n + lat_s) / 2.0))
            z = int(round(math.log2(360.0 * 111320.0 * coslat / (256.0 * step))))
            z = max(6, min(12, z))
        else:
            z = self.zoom
        n = 2 ** z
        x0 = int(math.floor((lon0 + 180.0) / 360.0 * n))
        x1 = int(math.floor((lon1 + 180.0) / 360.0 * n))
        y_n = self._y_of_lat(lat_n, n)
        y_s = self._y_of_lat(lat_s, n)
        yt = int(math.floor(min(y_n, y_s)))
        yb = int(math.floor(max(y_n, y_s)))
        elev = np.full((ny, nx), np.nan, dtype=np.float32)
        ntiles = 0
        for ty in range(yt, yb + 1):
            for tx in range(x0, x1 + 1):
                fn = self._fetch(z, tx, ty)
                if not fn:
                    continue
                try:
                    with PIL.Image.open(fn) as im:
                        a = np.asarray(im.convert("RGB"), dtype=np.float32)
                except Exception:
                    continue
                h = (a[:, :, 0] * 256.0 + a[:, :, 1] + a[:, :, 2] / 256.0) - 32768.0
                lon_l = tx / n * 360.0 - 180.0
                lon_r = (tx + 1) / n * 360.0 - 180.0
                lat_t = self._lat_of_y(ty, n)
                lat_b = self._lat_of_y(ty + 1, n)
                lons = lon_l + (np.arange(256) + 0.5) / 256.0 * (lon_r - lon_l)
                lats = lat_t - (np.arange(256) + 0.5) / 256.0 * (lat_t - lat_b)
                LON, LAT = np.meshgrid(lons, lats)
                X = LON * mPerLon
                Y = LAT * mPerLat
                ii = np.floor((X - x_min) / step).astype(np.int32)
                jj = np.floor((Y - y_min) / step).astype(np.int32)
                valid = (ii >= 0) & (ii < nx) & (jj >= 0) & (jj < ny)
                elev[jj[valid], ii[valid]] = h[valid]
                ntiles += 1
        print(f"  Terrarium: {ntiles} Kacheln, {int(np.isfinite(elev).sum())} Zellen mit Hoehe", file=sys.stderr)
        return elev


# ---------------------------------------------------------------------------
# River geometry
# ---------------------------------------------------------------------------
class River:
    """Laedt die Rhein-Geometrie (rhein.json) und baut die Fluss-Maske."""
    def __init__(self, file):
        with open(file, encoding="utf-8") as f:
            d = json.load(f)
        self.data = d
        self.ways = d.get("ways", [])
        self.lon_min = self.lon_max = self.ways[0][0][0]
        self.lat_min = self.lat_max = self.ways[0][0][1]
        for w in self.ways:
            for p in w:
                self.lon_min = min(self.lon_min, p[0]); self.lon_max = max(self.lon_max, p[0])
                self.lat_min = min(self.lat_min, p[1]); self.lat_max = max(self.lat_max, p[1])

    def mask(self, x_min, y_min, step, nx, ny, mPerLon, mPerLat):
        return build_river_mask(self.ways, x_min, y_min, step, nx, ny, mPerLon, mPerLat)


# ---------------------------------------------------------------------------
# Contour generation pipeline
# ---------------------------------------------------------------------------
class ContourGenerator:
    def __init__(self, river, sampler, interval=100, smooth=500, buffer=3000,
                 step=200, expand=6000):
        self.river = river
        self.sampler = sampler
        self.interval = interval
        self.smooth = smooth
        self.buffer = buffer
        self.step = step
        self.expand = expand

        lat_c = (river.lat_min + river.lat_max) / 2.0
        self.mPerLon = 111320.0 * math.cos(math.radians(lat_c))
        self.mPerLat = 110570.0

        x_min = river.lon_min * self.mPerLon - expand
        x_max = river.lon_max * self.mPerLon + expand
        y_min = river.lat_min * self.mPerLat - expand
        y_max = river.lat_max * self.mPerLat + expand
        self.x_min, self.y_min = x_min, y_min
        self.nx = int(math.ceil((x_max - x_min) / step)) + 1
        self.ny = int(math.ceil((y_max - y_min) / step)) + 1
        print(f"  Raster {self.nx}x{self.ny} bei {step} m ({self.nx*self.ny/1e6:.1f} Mio Zellen)", file=sys.stderr)

    def run(self):
        elev = self.sampler.sample_grid(self.x_min, self.y_min, self.step,
                                        self.nx, self.ny, self.mPerLon, self.mPerLat)
        covered = ~np.isnan(elev)
        print(f"  abgedeckte Zellen: {int(covered.sum())}", file=sys.stderr)

        sigma = self.smooth / self.step
        filled = np.nan_to_num(elev, nan=0.0)
        field = gaussian_approx(filled, sigma)
        maxima = local_maxima(elev, covered)
        field[maxima] = elev[maxima]
        print(f"  Feld: Max {float(np.nanmax(field[covered])):.0f} m, {int(maxima.sum())} lokale Maxima aus FABDEM erhalten", file=sys.stderr)

        river_mask = self.river.mask(self.x_min, self.y_min, self.step, self.nx, self.ny,
                                     self.mPerLon, self.mPerLat)
        n = max(1, int(round(self.buffer / self.step)))
        near = river_mask.astype(np.uint8)
        for _ in range(n):
            near = dilate3x3(near)
        near = near.astype(bool)
        interest = dilate3x3(near.astype(np.uint8)).astype(bool)
        print(f"  'Rhein-naehe'-Zellen (Puffer {self.buffer:.0f} m): {int(near.sum())}", file=sys.stderr)

        fmin = float(np.nanmin(elev[covered]))
        fmax = float(np.nanmax(elev[covered]))
        cells = [tuple(c) for c in np.argwhere(interest)]
        print(f"  zu durchsuchende Zellen pro Hoehe: {len(cells)}", file=sys.stderr)

        levels = []
        L = math.ceil(fmin / self.interval) * self.interval
        total = 0
        while L <= fmax:
            segs_idx = march_level(field, L, cells)
            kept = []
            for (p0, p1) in segs_idx:
                mi = int(round((p0[1] + p1[1]) / 2)); mi = min(max(mi, 0), self.ny - 1)
                mj = int(round((p0[0] + p1[0]) / 2)); mj = min(max(mj, 0), self.nx - 1)
                i0 = min(max(int(round(p0[0])), 0), self.nx - 1); j0 = min(max(int(round(p0[1])), 0), self.ny - 1)
                i1 = min(max(int(round(p1[0])), 0), self.nx - 1); j1 = min(max(int(round(p1[1])), 0), self.ny - 1)
                if near[j0, i0] or near[j1, i1] or near[mi, mj]:
                    lon0 = (self.x_min + p0[0] * self.step) / self.mPerLon
                    lat0 = (self.y_min + p0[1] * self.step) / self.mPerLat
                    lon1 = (self.x_min + p1[0] * self.step) / self.mPerLon
                    lat1 = (self.y_min + p1[1] * self.step) / self.mPerLat
                    kept.append([[round(lon0, 6), round(lat0, 6)], [round(lon1, 6), round(lat1, 6)]])
            if kept:
                levels.append({"elev": round(L, 1), "segments": kept})
                total += len(kept)
            L += self.interval

        out = {
            "interval_m": self.interval,
            "smooth_m": self.smooth,
            "buffer_m": self.buffer,
            "levels": levels,
        }
        print(f"  {len(levels)} Hoehenlinien, {total} Segmente", file=sys.stderr)
        return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="FABDEM-Isolinien (Hoehenlinien) des Rheins, nur entlang des Flusses, geglaettet.")
    ap.add_argument("file", help="rhein.json (Flussgeometrie)")
    ap.add_argument("interval", type=float, default=100, help="Hoehenintervall in m")
    ap.add_argument("smooth", type=float, default=500, help="Glaettung in m (x/y)")
    ap.add_argument("buffer", type=float, nargs="?", default=3000,
                    help="Puffer um den Rhein in m, in dem Isolinien behalten werden")
    ap.add_argument("--out", default="river_contours.json")
    ap.add_argument("--grid", type=float, default=200, help="Rasterweite in m")
    ap.add_argument("--expand", type=float, default=6000, help="Rand in m um die Flussbbox")
    ap.add_argument("--source", default="fabdem", choices=["fabdem", "terrarium"],
                    help="Hoehenquelle: FABDEM-Kacheln (dem/) oder globale Terrarium-Kacheln")
    ap.add_argument("--zoom", type=int, default=None, help="Terrarium-Zoom (sonst automatisch)")
    args = ap.parse_args()

    river = River(args.file)
    if args.source == "terrarium":
        sampler = TerrariumSampler("dem_terrarium", zoom=args.zoom)
    else:
        sampler = FabdemSampler("dem")
    gen = ContourGenerator(river, sampler, interval=args.interval, smooth=args.smooth,
                           buffer=args.buffer, step=args.grid, expand=args.expand)
    out = gen.run()
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"  -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
