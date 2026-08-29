"""Glaettet die Rhein-Hoehen in rhein.json (gleitender Mittelwert + Ausreisser).

Schreibt die geglaetteten Hoehen und Abfallraten zurueck in dieselbe Datei.
"""

import json
import math
import argparse


def seg_len(a, b):
    dx = (a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2)) * 111.32
    dy = (a[1] - b[1]) * 110.57
    return math.hypot(dx, dy)


def moving_avg(elev, cum, half):
    """Zentrierter gleitender Mittelwert ueber Pfaddistanz +/- half (Meter)."""
    n = len(elev)
    out = [0.0] * n
    lo = 0
    for i in range(n):
        while lo < i and cum[lo] < cum[i] - half:
            lo += 1
        hi = i
        s = 0.0
        c = 0
        while hi < n and cum[hi] <= cum[i] + half:
            s += elev[hi]
            c += 1
            hi += 1
        out[i] = s / c if c else elev[i]
    return out


def smooth_way(way, w1, w2, thresh):
    n = len(way)
    if n == 0:
        return way
    elev = [p[2] for p in way]
    cum = [0.0]
    for i in range(1, n):
        cum.append(cum[-1] + seg_len(way[i - 1], way[i]))

    # 1. Pass: gleitender Mittelwert ueber Fenster w1 (z.B. 300 m)
    s1 = moving_avg(elev, cum, w1 / 2.0)
    # 2. Pass: falls Ausreisser uebrig bleiben, 1km-Mittelwert (w2) nutzen
    s2 = moving_avg(elev, cum, w2 / 2.0)

    final = [0.0] * n
    fixed = 0
    for i in range(n):
        if abs(elev[i] - s1[i]) > thresh:
            final[i] = s2[i]
            fixed += 1
        else:
            final[i] = s1[i]

    # Abfallrate (m/km) als Steigung ueber das 300m-Fenster (w1) aus den
    # geglaetteten Hoehen; negativ (Ausreisser/Lake) wird auf 0 geklemmt.
    def interp(target):
        if target <= cum[0]:
            return final[0]
        if target >= cum[-1]:
            return final[-1]
        for k in range(1, n):
            if cum[k] >= target:
                if cum[k] == cum[k - 1]:
                    return final[k]
                t = (target - cum[k - 1]) / (cum[k] - cum[k - 1])
                return final[k - 1] + t * (final[k] - final[k - 1])
        return final[-1]

    half = w1 / 2.0
    desc = [0.0] * n
    for k in range(n):
        el = interp(cum[k] - half)
        er = interp(cum[k] + half)
        dkm = (cum[k] + half) - (cum[k] - half)
        rate = (el - er) / dkm * 1000.0 if dkm > 0 else 0.0
        desc[k] = rate if rate > 0 else 0.0

    out = []
    for i in range(n):
        out.append([
            round(way[i][0], 6),
            round(way[i][1], 6),
            round(final[i], 1),
            round(desc[i], 2),
        ])
    return out, fixed


def main():
    ap = argparse.ArgumentParser(description="Glaettet Rhein-Hoehen (FABDEM) und entfernt Ausreisser.")
    ap.add_argument("file", help="Pfad zur rhein.json")
    ap.add_argument("--w1", type=float, default=300, help="Fenster 1. Pass (m)")
    ap.add_argument("--w2", type=float, default=1000, help="Fenster 2. Pass / Ausreisser (m)")
    ap.add_argument("--thresh", type=float, default=30, help="Ausreisser-Schwelle gegen 1. Pass (m)")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        d = json.load(f)
    ways = d.get("ways", [])

    new_ways = []
    total_fixed = 0
    for w in ways:
        sw, fixed = smooth_way(w, args.w1, args.w2, args.thresh)
        new_ways.append(sw)
        total_fixed += fixed
    d["ways"] = new_ways

    allv = [p[2] for w in new_ways for p in w]
    d["elev_min"] = round(min(allv), 1)
    d["elev_max"] = round(max(allv), 1)

    with open(args.file, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)

    alld = [p[3] for w in new_ways for p in w]
    print(f"{args.file}: {len(new_ways)} Wege, {len(allv)} Punkte")
    print(f"  Ausreisser mit 1km-Pass behoben: {total_fixed}")
    print(f"  Hoehenbereich: {d['elev_min']} .. {d['elev_max']} m")
    print(f"  Abfallrate min/max: {min(alld):.1f} .. {max(alld):.1f} m/km")


if __name__ == "__main__":
    main()
