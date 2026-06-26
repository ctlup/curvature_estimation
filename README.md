# Road Curvature and Gradient from Dashcam

Extracts GPS and accelerometer data from dashcam video files and computes road curvature, slope gradient, and g-forces at each GPS fix. Output is a CSV per clip and an HTML map you can open in a browser.

---

## What it does

The dashcam stores GPS coordinates, speed, heading, altitude, and accelerometer readings directly inside the video file as metadata. The tool reads that embedded data using ExifTool and computes:

- **Curvature radius R** — how sharp each curve is, in metres
- **Slope / gradient** — how steep the road is, in percent and degrees
- **G-forces** — lateral (cornering), longitudinal (braking/acceleration), and vertical (calibration)

---

## Curvature

### How R is calculated

Small R means a tight turn. Large R means the road is nearly straight. Blank means straight (R above 1500 m).

| Situation | Typical R |
|---|---|
| Tight roundabout or hairpin | 10–20 m |
| Urban intersection turn | 20–50 m |
| Normal road curve | 100–300 m |
| Motorway on-ramp | 400–800 m |
| Straight road | blank |

**Method 1 — heading rate (primary)**

When the dashcam records compass bearing at each GPS fix, R comes from the physics of circular motion:

```
R = v / ω
```

where `v` is speed in m/s and `ω` is how fast the bearing is rotating in rad/s. This is the standard method used in road safety and naturalistic driving research (SHRP2, Euro NCAP assessments). It is preferred because heading from a GPS chip is more accurate than position differences, especially at low speeds.

**Method 2 — three-point circumradius (fallback)**

When heading is not recorded, three consecutive GPS positions define a triangle. The radius of the circle that passes through all three vertices is R:

```
R = (a × b × c) / (4 × A)
```

where a, b, c are the side lengths and A is the signed area of the triangle (sign encodes left vs right). GPS coordinates are projected to local metres and smoothed before computing.

In practice this dashcam records heading on ~95% of samples so Method 1 is used almost everywhere.

### OSM cross-check

Each GPS point is matched to the nearest road segment from OpenStreetMap and an independent R is computed from the OSM road geometry. This gives a second opinion — useful for spotting GPS glitches or confirming real curves. OSM data is fetched once via the Overpass API and cached locally.

---

## Slope and Gradient

### How slope is calculated

Altitude is recorded at every GPS fix by the dashcam GPS chip. Ground distance between consecutive points is computed using the Haversine formula:

```
d = 2 × R_earth × arcsin( sqrt( sin²(Δlat/2) + cos(lat1) × cos(lat2) × sin²(Δlon/2) ) )
```

Slope is then:

```
slope (%) = (Δaltitude / d) × 100
slope (°) = arctan(Δaltitude / d)
```

Samples where `|slope| > 25%` are flagged as GPS noise spikes and excluded. In practice fewer than 3 spikes occur per 180-second clip.

### Altitude validation

GPS altitude was validated against SRTM30m satellite elevation data (OpenTopoData API)-

### G-forces

The dashcam embeds 3-axis accelerometer readings at every 0.1-second interval in 6-value blocks `[gyro_x, gyro_y, gyro_z, acc_x, acc_y, acc_z]`. Raw counts are converted to g units:

```
g = raw_count / 2048
```

Axis layout (dashcam mounted on windshield):

| Axis | Direction | At rest |
|---|---|---|
| acc_x | Vertical | ≈ +1 g (gravity) |
| acc_y | Lateral | ≈ 0 g |
| acc_z | Longitudinal | ≈ 0 g |

The scale factor (2048 counts/g) was verified: the vertical axis reads 0.978 g at rest across all clips, within 2.2% of the theoretical 1 g.

---

## Output

### Curvature — `*_curvature.csv`

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

### Enriched telemetry — `*_enriched.csv`

| Column | Description |
|---|---|
| `t` | Time from start of clip (seconds) |
| `lat`, `lon` | GPS position |
| `altitude_m` | GPS altitude (metres) |
| `speed_kmh` | Vehicle speed |
| `heading_deg` | Compass bearing |
| `gps_dop` | Dilution of precision (lower = better) |
| `gps_sats` | Number of satellites |
| `dist_m` | Distance from previous point (m) |
| `arc_m` | Arc length since previous sample (m) |
| `slope_pct` | Road gradient (%). Positive = uphill |
| `slope_deg` | Road gradient (degrees) |
| `g_vertical` | Vertical g-force (≈ 1 g at rest) |
| `g_lateral` | Lateral g-force (cornering) |
| `g_longitudinal` | Longitudinal g-force (braking/acceleration) |
| `g_lateral_peak` | Peak lateral g within the 0.1 s window |
| `g_long_peak` | Peak longitudinal g within the 0.1 s window |
| `in_curve` | `True` if R_gps is present in the curvature CSV |

### Batch summary — `batch_summary.csv`

One row per clip: sample count, curve count, minimum R, and clip duration.

---

## Setup

Requires Python 3.8+ and [ExifTool](https://exiftool.org) on PATH.

```bash
python -m venv venv
venv\Scripts\pip install numpy requests matplotlib folium
```

---

## Usage

**Curvature — single video:**
```bash
venv\Scripts\python run_curvature.py data\clip.mp4
```

**Curvature — whole folder:**
```bash
venv\Scripts\python batch_process.py data\ -o output\ --maps
```

**Slope, gradient and g-forces:**
```bash
venv\Scripts\python enrich_telemetry.py data\clip.mp4
venv\Scripts\python enrich_telemetry.py data\clip.mp4 --curvature-csv output\clip_curvature.csv
```

---

## Files

| File | Purpose |
|---|---|
| `metadata_extract.py` | Reads GPS/accelerometer from video via ExifTool |
| `osm_curvature.py` | Computes R from GPS and from OSM road geometry |
| `run_curvature.py` | Entry point for a single video |
| `batch_process.py` | Processes a whole folder of videos |
| `validate_curvature.py` | Generates the HTML map and diagnostic chart |
| `enrich_telemetry.py` | Extracts altitude, slope, gradient, and g-forces |
| `osm_cache/` | Cached OSM road data (one file per route area) |
| `output/` | Generated CSVs and maps |

---


```
https://htmlpreview.github.io/?https://github.com/ctlup/curvature_estimation/blob/main/output/240829_101922_001_FH_map.html
```
