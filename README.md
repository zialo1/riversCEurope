# Rhein — 3D-Datenvisualisierung

Projekt zur 3D-Darstellung des Gefälle und des Verlaufs von Flüssen im Herzen Europas.

Die Flussgeometrie wird aus OpenStreetMap (Overpass API, Relation `Rhein`)
geladen. Als Höhe (Z-Wert) wird aus FABDEM bezogen oder bei schwierigkeiten linear interpoliert:
**2000 m an der Quelle**

## Starten

ES-Module laden nicht über `file://`, daher eine lokale Server-Instanz nutzen:

```powershell
# Variante A: Python
python -m http.server 8000

Dann `http://localhost:8000` im Browser öffnen.

# Variante B: Github Pages
https://zialo1.github.io/eduriversCEU/
```


## Weitere Flüsse hinzufügen

Mit beiliegenden Python Scripts können weitere Flüsse dazugefügt werden. Es entstehen durch die Tools json Files.
Diese müssen in Conf.yaml eingepflegt werden. Die Fluss-JSON Datei können mit dem python script smooth2.py geglättet werden.
Bitte alle Daten dann in newrivers und einem unterverzeichnis für andere hochladen. Die Dateien in diesem Verzeichnis müssen Benutzer dann ins Verzeichnis serverhtml kopieren und die alten Dateien mit dem gleichen Namen überschreiben. Zu den
Dateien gehören auch die Contours Files.

## Zukünftige Schritte.
Contour Dateien abschalten, besser anzeigen oder bessere JSON files generieren.


## Skripte für Generierung von Daten

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

- **Flüsse** Flüsse mit ihrer Steigung.
- **Seen** gefüllt, inkl. Beschriftung.
- **Städte**: entlang des Rheins (≤ 10 km), aber nur die „Rekord“-Städte —
  eine Stadt wird nur gezeigt, wenn ihre Einwohnerzahl größer ist als die
  aller zuvor flussabwärts liegenden Städte. Städte auf einem See werden
  ausgeblendet (stattdessen See-Name).

## Bedienung

- Maus: drehen / zoomen (OrbitControls, Auto-Rotation)
- Klick auf die Legende oder Pfeiltasten: Höhen-SchnittEbene —
  es bleibt der Flussabschnitt bis zur gewählten Höhe sichtbar.
- Innerhalb der Schweiz können die Abflussdaten live angezeigt werden wo vorhanden.

## Struktur

- `index.html` — Einstiegspunkt mit three.js Importmap (CDN)
- `main.js` — Szene, Kamera, Rhein, Grenzen, Seen, Städte, OrbitControls, Clipping
- `rhein.json` — Rhein-Koordinaten aus OSM (lon, lat, höhe)
- `geo.json` — Grenzen/Seen/Städte aus Natural Earth
- `fetch_rhein.py`, `fetch_geo.py` — Skripte zum Abrufen der Daten
