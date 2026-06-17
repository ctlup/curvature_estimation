import argparse
import os
import sys

from metadata_extract import extract
from osm_curvature import samples_from_telemetry, process_trace, write_csv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="video file (.mp4) or pre-extracted exiftool .json")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--no-osm", action="store_true")
    ap.add_argument("--cache", default="./osm_cache")
    args = ap.parse_args()

    try:
        telemetry = extract(args.input)
    except RuntimeError as e:
        sys.exit(str(e))

    samples = samples_from_telemetry(telemetry)
    if not samples:
        sys.exit("No GPS samples found. Is GPSStamp on for this clip?")

    print("Loaded {} GPS samples ({:.1f}s -> {:.1f}s).".format(
        len(samples), samples[0].t, samples[-1].t))
    have_hdg = sum(1 for s in samples if s.heading_deg is not None)
    method = "heading" if have_hdg > len(samples) // 2 else "position fallback"
    print("Heading available on {}/{} samples (using {}).".format(
        have_hdg, len(samples), method))

    rows = process_trace(samples, use_osm=not args.no_osm,
                         cache_dir=None if args.no_osm else args.cache)

    out = args.output or (os.path.splitext(os.path.basename(args.input))[0]
                          + "_curvature.csv")
    write_csv(rows, out)

    curves = [r for r in rows if r.R_gps != float('inf')]
    if curves:
        tightest = min(curves, key=lambda r: r.R_gps)
        print("Wrote {}: {} rows, {} in-curve.".format(out, len(rows), len(curves)))
        print("Tightest GPS curve: R={} m ({}) at t={}s, {} km/h.".format(
            tightest.R_gps, tightest.dir_gps, tightest.t, tightest.speed_kmh))
    else:
        print("Wrote {}: {} rows (mostly straight).".format(out, len(rows)))


if __name__ == "__main__":
    main()
