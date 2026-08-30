import json
import sys
from pathlib import Path


def convert_to_geojson(input_file, output_file):
    # --------------------------------------------------------
    # Load input JSON
    # --------------------------------------------------------

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "ways" not in data:
        raise ValueError("Input JSON does not contain 'ways'.")

    if not isinstance(data["ways"], list):
        raise ValueError("'ways' must be a list.")

    features = []

    # --------------------------------------------------------
    # Convert every way to a GeoJSON LineString
    # --------------------------------------------------------

    for way_index, way in enumerate(data["ways"]):

        if not isinstance(way, list):
            continue

        coordinates = []

        for node in way:

            if not isinstance(node, list) or len(node) < 3:
                continue

            lon = node[0]
            lat = node[1]
            altitude = node[2]

            if not all(
                isinstance(x, (int, float))
                for x in (lon, lat, altitude)
            ):
                continue

            # GeoJSON coordinate:
            # [longitude, latitude, altitude]
            coordinates.append([
                lon,
                lat,
                altitude
            ])

        # A LineString needs at least two coordinates.
        if len(coordinates) < 2:
            continue

        # ----------------------------------------------------
        # Keep all additional node fields.
        #
        # If your nodes contain:
        #
        # [lon, lat, altitude, field4, field5, ...]
        #
        # they are stored in the properties.
        # ----------------------------------------------------

        extra_fields = []

        for node in way:
            if len(node) > 3:
                extra_fields.append(node[3:])

        properties = {
            "way_index": way_index
        }

        if any(extra_fields):
            properties["extra_fields"] = extra_fields

        # ----------------------------------------------------
        # Create GeoJSON feature
        # ----------------------------------------------------

        feature = {
            "type": "Feature",
            "properties": properties,
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates
            }
        }

        features.append(feature)

    # --------------------------------------------------------
    # Create FeatureCollection
    # --------------------------------------------------------

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    # --------------------------------------------------------
    # Write output
    # --------------------------------------------------------

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            geojson,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(f"Converted {len(features)} ways.")
    print(f"Written to: {output_file}")


# ============================================================
# Command line
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 3:
        print(
            f"Usage:\n"
            f"  python {Path(sys.argv[0]).name} "
            f"input.json output.geojson"
        )
        sys.exit(1)

    convert_to_geojson(
        sys.argv[1],
        sys.argv[2]
    )
