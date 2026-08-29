# Rhein — 3D-Datenvisualisierung

Three.js-Projekt zur 3D-Darstellung des Rheins im Browser (Firefox/Chrome).

Die Flussgeometrie wird aus OpenStreetMap (Overpass API, Relation `Rhein`)
geladen. Als Höhe (Z-Wert) wird linear interpoliert: **2000 m an der Quelle**
(Schweiz, Vorderrhein/Tomasee) bis **0 m an der Mündung** (Nordsee bei Rotterdam).
Die Höhe entlang des Flusses ergibt sich aus der kürzesten Weglänge zum Quell-Knoten.

## Starten

ES-Module laden nicht über `file://`, daher eine lokale Server-Instanz nutzen:

```powershell
# Variante A: Python
python -m http.server 8000

# Variante B: Node
npx serve .
```

Dann `http://localhost:8000` im Browser öffnen.

## Daten neu laden

- `fetch_rhein.py` lädt die OSM-Relation `Rhein` (Overpass API) und schreibt
  `rhein.json` (flache Liste von `[lon, lat, hoehe_m]`, Höhe 2000 m Quelle → 0 m Mündung):
  ```powershell
  python fetch_rhein.py
  ```
- `fetch_geo.py` lädt Ländergrenzen, Seen und Städte aus Natural Earth
  (Name `geo.json`):
  ```powershell
  python fetch_geo.py
  ```

## Was wird gezeigt

- **Rhein** als Punktwolke + Linienzug, Höhe linear 2000 m (Quelle) → 0 m (Mündung).
- **Ländergrenzen** (admin_level 2) als Linien.
- **Seen** gefüllt, inkl. Beschriftung.
- **Städte**: entlang des Rheins (≤ 10 km), aber nur die „Rekord“-Städte —
  eine Stadt wird nur gezeigt, wenn ihre Einwohnerzahl größer ist als die
  aller zuvor flussabwärts liegenden Städte. Städte auf einem See werden
  ausgeblendet (stattdessen See-Name).

## Bedienung

- Maus: drehen / zoomen (OrbitControls, Auto-Rotation)
- Klick auf die Legende oder Pfeiltasten: Höhen-SchnittEbene —
  es bleibt der Flussabschnitt bis zur gewählten Höhe sichtbar.

## Struktur

- `index.html` — Einstiegspunkt mit three.js Importmap (CDN)
- `main.js` — Szene, Kamera, Rhein, Grenzen, Seen, Städte, OrbitControls, Clipping
- `rhein.json` — Rhein-Koordinaten aus OSM (lon, lat, höhe)
- `geo.json` — Grenzen/Seen/Städte aus Natural Earth
- `fetch_rhein.py`, `fetch_geo.py` — Skripte zum Abrufen der Daten
