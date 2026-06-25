import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys

# Nextbase 622GW: 6-value blocks [gyro_x, gyro_y, gyro_z, acc_x, acc_y, acc_z]
# acc_x reads ~2048 at rest (= 1 g vertical), confirmed across static samples
ACC_SCALE = 2048.0
ACC_X_IDX, ACC_Y_IDX, ACC_Z_IDX = 3, 4, 5


def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def parse_acc_block(raw_str):
    if not raw_str:
        return {}
    try:
        nums = [int(x) for x in str(raw_str).split()]
    except ValueError:
        return {}
    group = 6
    usable = (len(nums) // group) * group
    if usable == 0:
        return {}
    ax, ay, az = [], [], []
    for i in range(0, usable, group):
        b = nums[i:i + group]
        ax.append(b[ACC_X_IDX])
        ay.append(b[ACC_Y_IDX])
        az.append(b[ACC_Z_IDX])
    n = len(ax)
    ay_g = [v / ACC_SCALE for v in ay]
    az_g = [v / ACC_SCALE for v in az]
    return {
        "g_vertical":      round(sum(v / ACC_SCALE for v in ax) / n, 4),
        "g_lateral":       round(sum(ay_g) / n, 4),
        "g_longitudinal":  round(sum(az_g) / n, 4),
        "g_lateral_peak":  round(max(abs(v) for v in ay_g), 4),
        "g_long_peak":     round(max(abs(v) for v in az_g), 4),
    }


def run_exiftool(video_path):
    result = subprocess.run(
        ["exiftool", "-ee", "-j", "-G3", video_path],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        sys.exit("ExifTool failed: " + result.stderr[:300])
    return json.loads(result.stdout)


def dms_to_deg(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"\s*([\d.]+)\s*deg\s*([\d.]+)'\s*([\d.]+)\"?\s*([NSEW])", str(value))
    if not m:
        try:
            return float(value)
        except ValueError:
            return None
    d, mm, ss, hemi = float(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4)
    val = d + mm / 60.0 + ss / 3600.0
    return -val if hemi in ("S", "W") else val


def to_float(v, default=None):
    if v is None:
        return default
    try:
        return float(str(v).replace("s", "").replace("m", "").strip())
    except ValueError:
        return default


def gps_epoch(dt_str):
    if not dt_str:
        return None
    try:
        from datetime import datetime, timezone
        s = dt_str.rstrip("Z").replace(":", "-", 2)
        fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in s else "%Y-%m-%d %H:%M:%S"
        return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def extract_samples(video_path):
    blocks = run_exiftool(video_path)
    if isinstance(blocks, list) and len(blocks) == 1:
        docs = {}
        for key, val in blocks[0].items():
            m = re.match(r"^(Doc\d+):(.+)$", key)
            if m:
                docs.setdefault(m.group(1), {})[m.group(2)] = val
        blocks = list(docs.values())

    raw = []
    for b in blocks:
        lat = dms_to_deg(b.get("GPSLatitude"))
        lon = dms_to_deg(b.get("GPSLongitude"))
        if lat is None or lon is None:
            continue
        raw.append({
            "t":       to_float(b.get("SampleTime")),
            "epoch":   gps_epoch(b.get("GPSDateTime")),
            "lat":     lat,
            "lon":     lon,
            "speed":   to_float(b.get("GPSSpeed"), 0.0),
            "heading": to_float(b.get("GPSTrack")),
            "alt":     to_float(b.get("GPSAltitude")),
            "dop":     to_float(b.get("GPSDOP")),
            "sats":    b.get("GPSSatellites"),
            "acc_raw": b.get("AccelerometerData", ""),
        })

    epoch0 = next((r["epoch"] for r in raw if r["t"] == 0.0 and r["epoch"]), None)
    if epoch0 is None:
        epoch0 = next((r["epoch"] for r in raw if r["epoch"]), None)
    for r in raw:
        if r["t"] is None and r["epoch"] and epoch0:
            r["t"] = r["epoch"] - epoch0
        r["t"] = r["t"] or 0.0

    raw.sort(key=lambda r: r["t"])
    return [r for r in raw if r["t"] >= 0]


def enrich(samples):
    rows = []
    for i, s in enumerate(samples):
        prev = samples[i - 1] if i > 0 else None

        dist = haversine(prev["lat"], prev["lon"], s["lat"], s["lon"]) if prev else 0.0

        slope_pct = slope_deg = None
        if prev and prev["alt"] is not None and s["alt"] is not None and dist > 0.5:
            dh = s["alt"] - prev["alt"]
            slope_pct = round((dh / dist) * 100, 2)
            slope_deg = round(math.degrees(math.atan2(dh, dist)), 3)

        acc = parse_acc_block(s["acc_raw"])
        dt = (s["t"] - prev["t"]) if prev else 0.0

        rows.append({
            "t":              round(s["t"], 3),
            "lat":            s["lat"],
            "lon":            s["lon"],
            "altitude_m":     s["alt"],
            "speed_kmh":      s["speed"],
            "heading_deg":    s["heading"],
            "gps_dop":        s["dop"],
            "gps_sats":       s["sats"],
            "dist_m":         round(dist, 3),
            "arc_m":          round((s["speed"] / 3.6) * dt if dt > 0 else 0.0, 3),
            "slope_pct":      slope_pct,
            "slope_deg":      slope_deg,
            "g_vertical":     acc.get("g_vertical"),
            "g_lateral":      acc.get("g_lateral"),
            "g_longitudinal": acc.get("g_longitudinal"),
            "g_lateral_peak": acc.get("g_lateral_peak"),
            "g_long_peak":    acc.get("g_long_peak"),
        })
    return rows


def add_curve_flags(rows, curvature_csv):
    if not os.path.exists(curvature_csv):
        return rows
    curve_times = set()
    with open(curvature_csv, newline="") as f:
        for r in csv.DictReader(f):
            if r["R_gps"]:
                curve_times.add(round(float(r["t"]), 1))
    for row in rows:
        row["in_curve"] = (round(row["t"], 1) in curve_times)
    return rows


def print_summary(rows):
    alts  = [r["altitude_m"] for r in rows if r["altitude_m"] is not None]
    slps  = [r["slope_pct"]  for r in rows if r["slope_pct"]  is not None]
    g_lat = [r["g_lateral"]  for r in rows if r["g_lateral"]  is not None]
    g_lon = [r["g_longitudinal"] for r in rows if r["g_longitudinal"] is not None]

    sep = "-" * 55
    print(f"\n{sep}")
    print(f"  Samples   : {len(rows)}")
    print(f"  Duration  : {rows[-1]['t']:.1f} s")
    if alts:
        print(f"  Altitude  : {min(alts):.1f} / {max(alts):.1f} m  (range {max(alts)-min(alts):.1f} m)")
    if slps:
        print(f"  Slope     : max +{max(slps):.2f}%  min {min(slps):.2f}%  mean |s| {sum(abs(s) for s in slps)/len(slps):.2f}%")
    if g_lat:
        print(f"  G lateral : {max(abs(v) for v in g_lat):.3f} g peak")
    if g_lon:
        print(f"  G long    : {max(abs(v) for v in g_lon):.3f} g peak")
    print(f"{sep}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="dashcam .mp4 file")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--curvature-csv", default=None)
    args = ap.parse_args()

    print(f"Extracting telemetry from {args.input} ...")
    samples = extract_samples(args.input)
    if not samples:
        sys.exit("No GPS samples found.")
    print(f"  {len(samples)} raw samples.")

    rows = enrich(samples)

    curv_csv = args.curvature_csv
    if curv_csv is None:
        stem = os.path.splitext(os.path.basename(args.input))[0]
        candidate = os.path.join("output", stem + "_curvature.csv")
        if os.path.exists(candidate):
            curv_csv = candidate
    if curv_csv:
        rows = add_curve_flags(rows, curv_csv)
        print(f"  Curve flags from {curv_csv}.")

    out = args.output or os.path.join(
        "output",
        os.path.splitext(os.path.basename(args.input))[0] + "_enriched.csv"
    )
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print_summary(rows)
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
