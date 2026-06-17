"""
Batch curvature extraction for a folder of dashcam videos.

Usage:
    python batch_process.py data/               # process all .mp4 in data/
    python batch_process.py data/ -o output/    # save CSVs to output/
    python batch_process.py data/ --no-osm      # skip OSM lookup (faster)
    python batch_process.py data/ --maps        # also generate HTML maps

All videos that cover the same area share one OSM cache file, so Overpass
is only contacted once per geographic region across the entire batch.
"""

import argparse
import csv
import math
import os
import sys
import time
from pathlib import Path

from metadata_extract import extract
from osm_curvature import samples_from_telemetry, process_trace, write_csv


SUPPORTED = {".mp4", ".mov", ".avi", ".mkv"}


def find_videos(input_path):
    p = Path(input_path)
    if p.is_file():
        return [p]
    return sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)


def process_one(video_path, out_dir, use_osm, cache_dir):
    stem = video_path.stem
    out_csv = out_dir / (stem + "_curvature.csv")

    if out_csv.exists():
        print(f"  [skip] {stem} — CSV already exists")
        return {"file": stem, "status": "skipped"}

    t0 = time.time()
    try:
        telemetry = extract(str(video_path))
    except RuntimeError as e:
        print(f"  [fail] {stem} — exiftool error: {e}")
        return {"file": stem, "status": "error", "reason": str(e)}

    samples = samples_from_telemetry(telemetry)
    if not samples:
        print(f"  [fail] {stem} — no GPS samples found")
        return {"file": stem, "status": "no_gps"}

    rows = process_trace(samples, use_osm=use_osm,
                         cache_dir=str(cache_dir) if use_osm else None)
    write_csv(rows, str(out_csv))

    curves = [r for r in rows if r.R_gps != math.inf]
    tightest_R = min(r.R_gps for r in curves) if curves else None
    duration = samples[-1].t - samples[0].t
    elapsed = time.time() - t0

    print(f"  [ok]   {stem} — {len(rows)} samples, {len(curves)} curves, "
          f"min R={tightest_R:.1f} m, {duration:.0f}s clip, done in {elapsed:.1f}s")

    return {
        "file":       stem,
        "status":     "ok",
        "n_samples":  len(rows),
        "n_curves":   len(curves),
        "min_R_m":    round(tightest_R, 1) if tightest_R else "",
        "duration_s": round(duration, 1),
        "csv":        str(out_csv),
    }


def write_summary(results, out_dir):
    path = out_dir / "batch_summary.csv"
    fields = ["file", "status", "n_samples", "n_curves", "min_R_m", "duration_s", "csv"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)
    print(f"\nSummary saved: {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="video file or folder of videos")
    ap.add_argument("-o", "--output", default="output",
                    help="output folder for CSVs (default: ./output)")
    ap.add_argument("--no-osm", action="store_true",
                    help="skip OSM lookup (faster, no internet needed)")
    ap.add_argument("--cache", default="./osm_cache",
                    help="OSM cache directory (shared across all videos)")
    ap.add_argument("--maps", action="store_true",
                    help="also generate _map.html for each video")
    args = ap.parse_args()

    videos = find_videos(args.input)
    if not videos:
        sys.exit(f"No supported video files found in: {args.input}")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache)

    print(f"Found {len(videos)} video(s) -> output: {out_dir}/")
    print(f"OSM: {'disabled' if args.no_osm else f'enabled (cache: {cache_dir})'}\n")

    results = []
    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {video.name}")
        result = process_one(video, out_dir, not args.no_osm, cache_dir)
        results.append(result)

    write_summary(results, out_dir)

    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = len(results) - ok - skipped
    print(f"\nDone: {ok} processed, {skipped} skipped (already existed), {failed} failed")

    if args.maps and ok > 0:
        print("\nGenerating maps...")
        from validate_curvature import load_csv, build_map
        for r in results:
            if r["status"] != "ok":
                continue
            try:
                rows = load_csv(r["csv"])
                map_path = r["csv"].replace("_curvature.csv", "_map.html")
                build_map(rows, map_path)
            except Exception as e:
                print(f"  Map failed for {r['file']}: {e}")


if __name__ == "__main__":
    main()
