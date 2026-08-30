import json
import math
import sys
from pathlib import Path

''' takes a river.json and reduces its size substantially '''


# ============================================================
# Configuration
# ============================================================

# Base tolerances
#
# Horizontal values are in meters.
# Altitude values are in the same unit as the input altitude.
#
# Requested scaling:
#   minimum tolerances × 100
#   maximum tolerances × 20
#
# Minimum tolerances for long segments.

MAX_HORIZONTAL_TOLERANCE = 5.0 * 4       # 20 m
MIN_HORIZONTAL_TOLERANCE = 0.1 * 200      # 20 m

MAX_ALT_TOLERANCE = 0.5 * 20              # 10 m
MIN_ALT_TOLERANCE = 0.05 * 300            # 15 m

# Distance at which the tolerance approaches its minimum.
DISTANCE_SCALE = 1000.0                   # meters

# Number of complete walkthroughs.
PASSES = 3

EARTH_RADIUS = 6371000.0


# ============================================================
# Local geographic projection
# ============================================================

def local_xy(lon, lat, lon0, lat0):
    """
    Convert longitude/latitude to local East/North meters.

    The projection is centered at lon0/lat0.

    This is a very fast local approximation and is appropriate
    for comparing nearby river nodes.
    """

    rad = math.pi / 180.0

    x = (
        (lon - lon0)
        * rad
        * EARTH_RADIUS
        * math.cos(lat0 * rad)
    )

    y = (
        (lat - lat0)
        * rad
        * EARTH_RADIUS
    )

    return x, y


def distance_local(a, c):
    """
    Calculate A-C distance in local meters.
    """

    lon0 = (a[0] + c[0]) / 2.0
    lat0 = (a[1] + c[1]) / 2.0

    ax, ay = local_xy(a[0], a[1], lon0, lat0)
    cx, cy = local_xy(c[0], c[1], lon0, lat0)

    dx = cx - ax
    dy = cy - ay

    return math.hypot(dx, dy)


# ============================================================
# Distance-dependent tolerance
# ============================================================

def inverse_tolerance(
    distance,
    max_tolerance,
    min_tolerance,
    scale=DISTANCE_SCALE,
):
    """
    Tolerance is larger for short distances and smaller for
    long distances.

    Formula:

        tolerance = max_tolerance * scale / (distance + scale)

    Then clamp to [min_tolerance, max_tolerance].
    """

    if distance <= 0:
        return max_tolerance

    tolerance = (
        max_tolerance
        * scale
        / (distance + scale)
    )

    return max(
        min_tolerance,
        min(max_tolerance, tolerance)
    )


# ============================================================
# Middle-node test
# ============================================================

def can_remove_middle_node(a, b, c):
    """
    Test whether B can be removed:

        A -> B -> C

    B must be close to the midpoint between A and C in:

        - local East coordinate
        - local North coordinate
        - altitude

    The horizontal tolerance is in meters.

    Altitude is checked independently and strictly.
    """

    # --------------------------------------------------------
    # Local coordinate system centered between A and C.
    # --------------------------------------------------------

    lon0 = (a[0] + c[0]) / 2.0
    lat0 = (a[1] + c[1]) / 2.0

    ax, ay = local_xy(a[0], a[1], lon0, lat0)
    bx, by = local_xy(b[0], b[1], lon0, lat0)
    cx, cy = local_xy(c[0], c[1], lon0, lat0)

    # --------------------------------------------------------
    # Midpoint of A and C.
    # --------------------------------------------------------

    avg_x = (ax + cx) / 2.0
    avg_y = (ay + cy) / 2.0
    avg_alt = (a[2] + c[2]) / 2.0

    # --------------------------------------------------------
    # Error of B from the A-C midpoint.
    # --------------------------------------------------------

    x_error = abs(bx - avg_x)
    y_error = abs(by - avg_y)
    alt_error = abs(b[2] - avg_alt)

    # --------------------------------------------------------
    # Distance that would result after removing B.
    # --------------------------------------------------------

    dx = cx - ax
    dy = cy - ay

    distance = math.hypot(dx, dy)

    # --------------------------------------------------------
    # Distance-dependent tolerances.
    #
    # Horizontal tolerance is the same in X/Y.
    # --------------------------------------------------------

    horizontal_tolerance = inverse_tolerance(
        distance,
        MAX_HORIZONTAL_TOLERANCE,
        MIN_HORIZONTAL_TOLERANCE,
    )

    altitude_tolerance = inverse_tolerance(
        distance,
        MAX_ALT_TOLERANCE,
        MIN_ALT_TOLERANCE,
    )

    # --------------------------------------------------------
    # All criteria must pass.
    # --------------------------------------------------------

    horizontal_ok = (
        x_error <= horizontal_tolerance
        and
        y_error <= horizontal_tolerance
    )

    altitude_ok = (
        alt_error <= altitude_tolerance
    )

    removable = horizontal_ok and altitude_ok

    return removable, {
        "distance": distance,

        "x_error": x_error,
        "y_error": y_error,
        "alt_error": alt_error,

        "horizontal_tolerance": horizontal_tolerance,
        "altitude_tolerance": altitude_tolerance,

        "horizontal_ok": horizontal_ok,
        "altitude_ok": altitude_ok,
    }


# ============================================================
# Simplify one way
# ============================================================

def simplify_way(nodes, passes=PASSES):
    """
    Simplify one way using a sliding 3-node window.

        A -> B -> C

    If B can be omitted, it is immediately deleted.

    The process is repeated for the requested number of passes.

    First and last nodes are never removed.
    """

    if len(nodes) <= 2:
        return nodes

    nodes = list(nodes)

    for pass_number in range(passes):

        original_count = len(nodes)

        i = 1

        while i < len(nodes) - 1:

            a = nodes[i - 1]
            b = nodes[i]
            c = nodes[i + 1]

            removable, diagnostics = can_remove_middle_node(
                a, b, c
            )

            if removable:

                # Remove B.
                del nodes[i]

                # Re-check around the removal.
                #
                # Example:
                #
                # A -> B -> C -> D
                #
                # after deleting B:
                #
                # A -> C -> D
                #
                # The new A-C-D relationship needs checking.
                if i > 1:
                    i -= 1

            else:
                i += 1

        removed = original_count - len(nodes)

        print(
            f"    pass {pass_number + 1}: "
            f"{original_count} -> {len(nodes)} "
            f"({removed} removed)"
        )

        # Stop early if nothing changed.
        if removed == 0:
            break

    return nodes


# ============================================================
# Load and simplify JSON
# ============================================================

def simplify_json(input_file, output_file):

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "ways" not in data:
        raise ValueError(
            "JSON does not contain a 'ways' field."
        )

    if not isinstance(data["ways"], list):
        raise ValueError(
            "'ways' must be a list."
        )

    total_before = 0
    total_after = 0

    # --------------------------------------------------------
    # Process every way independently.
    # --------------------------------------------------------

    for way_index, way in enumerate(data["ways"]):

        if not isinstance(way, list):
            print(
                f"Skipping way {way_index}: "
                f"not a list"
            )
            continue

        # ----------------------------------------------------
        # Nodes are:
        #
        # [longitude, latitude, altitude, ...]
        #
        # Everything after field 3 is preserved.
        # ----------------------------------------------------

        valid_nodes = []

        for node in way:

            if (
                isinstance(node, list)
                and len(node) >= 3
                and isinstance(node[0], (int, float))
                and isinstance(node[1], (int, float))
                and isinstance(node[2], (int, float))
            ):
                valid_nodes.append(node)

        if len(valid_nodes) < 3:
            continue

        before = len(valid_nodes)

        simplified = simplify_way(
            valid_nodes,
            passes=PASSES
        )

        after = len(simplified)

        # Replace original way.
        data["ways"][way_index] = simplified

        total_before += before
        total_after += after

        print(
            f"way {way_index}: "
            f"{before} -> {after} "
            f"({before - after} removed)"
        )

    # --------------------------------------------------------
    # Statistics.
    # --------------------------------------------------------

    print()
    print("==============================")
    print("Simplification complete")
    print("==============================")
    print(f"Total nodes: {total_before} -> {total_after}")
    print(f"Removed:     {total_before - total_after}")

    if total_before:
        percentage = (
            100.0
            * (total_before - total_after)
            / total_before
        )

        print(f"Reduction:   {percentage:.2f}%")

    # --------------------------------------------------------
    # Save.
    # --------------------------------------------------------

    with open(output_file, "w", encoding="utf-8") as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            separators=(",", ":")
        )

    print(f"Written: {output_file}")


# ============================================================
# Command line
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 3:

        print(
            f"Usage:\n"
            f"  python {Path(sys.argv[0]).name} "
            f"input.json output.json"
        )

        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    simplify_json(
        input_file,
        output_file
    )
