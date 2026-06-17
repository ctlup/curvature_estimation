# Road Curvature from Dashcam

Extracts GPS data from dashcam video files and computes the road curvature at each point. Output is a CSV per clip and an HTML map you can open in a browser.

---

## What it does

The dashcam stores GPS coordinates, speed, and heading directly inside the video file as metadata. The tool reads that embedded data using ExifTool and calculates how sharp each curve is, expressed as a radius R in metres.

Small R means a tight turn. Large R means the road is nearly straight. Blank means straight (R above 1500 m).

Some reference values to get a feel for the numbers:

| Situation | Typical R |
|---|---|
| Tight roundabout or hairpin | 10–20 m |
| Urban intersection turn | 20–50 m |
| Normal road curve | 100–300 m |
| Motorway on-ramp | 400–800 m |
| Straight road | blank |

---

## How R is calculated

Two methods are used depending on what the dashcam recorded.

**Method 1 — heading rate (primary)**

If the dashcam records compass bearing at each GPS fix, R comes from the physics of circular motion:

```
R = v / ω
```

where `v` is speed in m/s and `ω` is how fast the bearing is rotating in rad/s. This is the standard method used in road safety and naturalistic driving research (SHRP2, Euro NCAP assessments). It is preferred because heading from a GPS chip is more accurate than position differences, especially at low speeds.

**Method 2 — three-point circumradius (fallback)**

When heading is not recorded, three consecutive GPS positions define a triangle. The radius of the circle that passes through all three vertices is R:

```
R = (a × b × c) / (4 × A)
```

where a, b, c are the side lengths and A is the area of the triangle (signed, so the sign tells you left vs right). Before computing, GPS coordinates are converted to local metres and lightly smoothed to reduce noise.

In practice this dashcam records heading on ~95% of samples so Method 1 is used almost everywhere.

---

## OSM cross-check

Each GPS point is also matched to the nearest road segment from OpenStreetMap and the OSM road geometry is used to compute an independent R for that segment. This gives a second opinion — useful for spotting GPS glitches (if GPS says R=15m on a straight motorway, something went wrong) or confirming real curves.

OSM data is fetched once via the Overpass API for the bounding box of the entire route and cached locally. All clips filmed in the same area reuse the cache, so Overpass is not called again.

---

## Output

Each video produces a `*_curvature.csv` with one row per GPS sample:

| Column | Description |
|---|---|
| `t` | Time from start of clip (seconds) |
| `lat`, `lon` | GPS position |
| `speed_kmh` | Vehicle speed |
| `R_gps` | Curve radius from GPS (m). Blank = straight |
| `dir_gps` | `left`, `right`, or `straight` |
| `R_osm` | Curve radius from OSM road geometry |
| `dir_osm` | Direction from OSM |
| `road_name` | Road name from OSM |
| `quality` | `ok`, `low_gps`, or `no_osm_match` |

The `*_map.html` shows the GPS track on a real map, coloured green (straight) to red (tight curve). Hover any segment for speed, R, and road name.

---

## Setup

Requires Python 3.8+ and [ExifTool](https://exiftool.org) on PATH.

```bash
python -m venv venv
venv\Scripts\pip install numpy requests matplotlib folium
```

---

## Usage

**Single video:**
```bash
venv\Scripts\python run_curvature.py data\clip.mp4
```

**Whole folder (batch):**
```bash
venv\Scripts\python batch_process.py data\ -o output\
venv\Scripts\python batch_process.py data\ -o output\ --maps   # also generate HTML maps
venv\Scripts\python batch_process.py data\ -o output\ --no-osm # skip OSM, GPS only
```

**Visualise a single result:**
```bash
venv\Scripts\python validate_curvature.py output\clip_curvature.csv
```

Batch produces `output/batch_summary.csv` — one row per clip with sample count, curve count, minimum R, and clip duration.

---

## Files

| File | Purpose |
|---|---|
| `metadata_extract.py` | Reads GPS/accelerometer from video via ExifTool |
| `osm_curvature.py` | Computes R from GPS and from OSM road geometry |
| `run_curvature.py` | Entry point for a single video |
| `batch_process.py` | Processes a whole folder of videos |
| `validate_curvature.py` | Generates the map and diagnostic chart |
| `osm_cache/` | Cached OSM road data (one file per route area) |
| `output/` | Generated CSVs and maps |
