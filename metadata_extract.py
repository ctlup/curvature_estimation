import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict, field
from shutil import which
from typing import Optional, List


@dataclass
class TelemetrySample:
    t: float
    lat: float
    lon: float
    speed_kmh: float = 0.0
    heading_deg: Optional[float] = None
    altitude_m: Optional[float] = None
    dop: Optional[float] = None
    sats: Optional[int] = None
    gps_time: Optional[str] = None
    acc0_mean: Optional[float] = None
    acc1_mean: Optional[float] = None
    acc2_mean: Optional[float] = None
    acc_mag_mean: Optional[float] = None
    acc_mag_max: Optional[float] = None
    acc_n: int = 0
    acc_raw: List[int] = field(default_factory=list)


def dms_to_deg(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"\s*([\d.]+)\s*deg\s*([\d.]+)'\s*([\d.]+)\"?\s*([NSEW])", value)
    if not m:
        try:
            return float(value)
        except ValueError:
            return None
    d, mm, ss, hemi = float(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4)
    val = d + mm / 60.0 + ss / 3600.0
    if hemi in ("S", "W"):
        val = -val
    return val


def _to_float(value, default=None):
    if value is None:
        return default
    s = str(value).strip()
    # H:MM:SS or H:MM:SS.f
    m = re.match(r'^(\d+):(\d+):(\d+(?:\.\d+)?)$', s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    try:
        return float(s.replace("s", "").replace("m", "").strip())
    except ValueError:
        return default


def _gps_datetime_to_epoch(dt_str):
    """Parse GPSDateTime string like '2024:08:29 08:18:44.600Z' to a float epoch."""
    if not dt_str:
        return None
    try:
        from datetime import datetime, timezone
        s = dt_str.rstrip("Z").replace(":", "-", 2)
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        try:
            from datetime import datetime, timezone
            s = dt_str.rstrip("Z").replace(":", "-", 2)
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return None


def parse_accelerometer(raw_str, group=6):
    if not raw_str:
        return {}
    try:
        nums = [int(x) for x in str(raw_str).split()]
    except ValueError:
        return {}
    if len(nums) < group:
        return {"acc_raw": nums, "acc_n": 0}
    usable = (len(nums) // group) * group
    axes = [[] for _ in range(group)]
    mags = []
    for i in range(0, usable, group):
        block = nums[i:i + group]
        for a in range(group):
            axes[a].append(block[a])
        mags.append(math.sqrt(block[0] ** 2 + block[1] ** 2 + block[2] ** 2))
    n = usable // group
    out = {
        "acc0_mean": sum(axes[0]) / n,
        "acc1_mean": sum(axes[1]) / n,
        "acc2_mean": sum(axes[2]) / n,
        "acc_mag_mean": sum(mags) / n,
        "acc_mag_max": max(mags),
        "acc_n": n,
        "acc_raw": nums,
    }
    return out


def run_exiftool(video_path):
    if which("exiftool") is None:
        raise RuntimeError("exiftool not found on PATH.")
    out = subprocess.run(["exiftool", "-ee", "-j", "-G3", video_path],
                         capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError("exiftool failed: " + out.stderr[:400])
    return json.loads(out.stdout)


def _unpack_g3(obj):
    """Convert a G3-format dict (Doc1000:GPSLatitude, ...) into per-doc dicts."""
    import re
    docs = {}
    for key, val in obj.items():
        m = re.match(r"^(Doc\d+):(.+)$", key)
        if m:
            doc_id, field = m.group(1), m.group(2)
            docs.setdefault(doc_id, {})[field] = val
    return list(docs.values())


def parse_blocks(blocks, keep_raw_acc=False) -> List[TelemetrySample]:
    if isinstance(blocks, list) and len(blocks) == 1 and isinstance(blocks[0], dict):
        first = blocks[0]
        if any(re.match(r"^Doc\d+:", k) for k in first.keys()):
            blocks = _unpack_g3(first)
    elif isinstance(blocks, dict):
        blocks = [blocks]
    raw = []
    for b in blocks:
        lat = dms_to_deg(b.get("GPSLatitude"))
        lon = dms_to_deg(b.get("GPSLongitude"))
        if lat is None or lon is None:
            continue
        t = _to_float(b.get("SampleTime"))
        spd = _to_float(b.get("GPSSpeed"), 0.0)
        hdg = _to_float(b.get("GPSTrack"))
        alt = _to_float(b.get("GPSAltitude"))
        dop = _to_float(b.get("GPSDOP"))
        sats = b.get("GPSSatellites")
        sats = int(sats) if sats is not None else None
        acc = parse_accelerometer(b.get("AccelerometerData"))
        if not keep_raw_acc:
            acc.pop("acc_raw", None)
        raw.append((t, _gps_datetime_to_epoch(b.get("GPSDateTime")),
                    lat, lon, spd, hdg, alt, dop, sats,
                    b.get("GPSDateTime"), acc))

    # Resolve timestamps: prefer SampleTime; fall back to GPSDateTime offset.
    # Anchor epoch0 to the GPSDateTime of the first sample that has SampleTime=0.
    epoch0 = next((ep for t, ep, *_ in raw if t == 0.0 and ep is not None), None)
    if epoch0 is None:
        epoch0 = next((ep for _, ep, *_ in raw if ep is not None), None)
    samples = []
    for t, epoch, lat, lon, spd, hdg, alt, dop, sats, gps_time, acc in raw:
        if t is None:
            t = (epoch - epoch0) if (epoch is not None and epoch0 is not None) else 0.0
        samples.append(TelemetrySample(
            t=t, lat=lat, lon=lon, speed_kmh=spd, heading_deg=hdg,
            altitude_m=alt, dop=dop, sats=sats, gps_time=gps_time,
            **{k: v for k, v in acc.items() if k != "acc_raw"},
            acc_raw=acc.get("acc_raw", []) if keep_raw_acc else []))
    samples.sort(key=lambda s: s.t)
    # Drop samples before clip start (pre-recording GPS cache from previous clip)
    samples = [s for s in samples if s.t >= 0]
    samples = _dedupe(samples)
    return _filter_jumps(samples)


def _dedupe(samples):
    seen, out = set(), []
    for s in samples:
        key = (round(s.lat, 7), round(s.lon, 7), round(s.t, 3))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _filter_jumps(samples, max_speed_kmh=250.0):
    """Remove samples that imply physically impossible speed from secondary GPS streams."""
    if not samples:
        return samples
    from osm_curvature import haversine
    max_ms = max_speed_kmh / 3.6
    out = [samples[0]]
    for s in samples[1:]:
        prev = out[-1]
        dt = s.t - prev.t
        dist = haversine(prev.lat, prev.lon, s.lat, s.lon)
        # Same timestamp: keep only if very close (< 10 m) to previous accepted point
        if dt == 0:
            if dist < 10:
                out.append(s)
            continue
        implied_speed = dist / dt
        if implied_speed <= max_ms:
            out.append(s)
    return out


def extract(source, keep_raw_acc=False) -> List[TelemetrySample]:
    if source.lower().endswith(".json"):
        with open(source) as f:
            blocks = json.load(f)
    else:
        blocks = run_exiftool(source)
    return parse_blocks(blocks, keep_raw_acc=keep_raw_acc)


def write_csv(samples: List[TelemetrySample], path, include_raw_acc=False):
    if not samples:
        raise ValueError("no samples to write")
    fields = [k for k in asdict(samples[0]).keys() if k != "acc_raw"]
    if include_raw_acc:
        fields.append("acc_raw")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in samples:
            d = asdict(s)
            row = {k: d[k] for k in fields if k != "acc_raw"}
            if include_raw_acc:
                row["acc_raw"] = " ".join(str(x) for x in d["acc_raw"])
            w.writerow(row)


def main():
    ap = argparse.ArgumentParser(
        description="Extract GPS + accelerometer + altitude telemetry from dashcam video.")
    ap.add_argument("input", help="video file (.mp4) or pre-extracted exiftool .json")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--raw-acc", action="store_true",
                    help="also write full raw accelerometer arrays")
    args = ap.parse_args()

    try:
        samples = extract(args.input, keep_raw_acc=args.raw_acc)
    except RuntimeError as e:
        sys.exit(str(e))

    if not samples:
        sys.exit("No GPS samples found. Is GPSStamp on for this clip?")

    out = args.output or (os.path.splitext(os.path.basename(args.input))[0]
                          + "_telemetry.csv")
    write_csv(samples, out, include_raw_acc=args.raw_acc)

    have_hdg = sum(1 for s in samples if s.heading_deg is not None)
    have_acc = sum(1 for s in samples if s.acc_n > 0)
    print("Extracted {} samples ({:.1f}s -> {:.1f}s).".format(
        len(samples), samples[0].t, samples[-1].t))
    print("  heading: {}/{}   accelerometer: {}/{}".format(
        have_hdg, len(samples), have_acc, len(samples)))
    print("Wrote {}".format(out))


if __name__ == "__main__":
    main()
