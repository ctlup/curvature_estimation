"""
Validate curvature extraction: GPS track overlaid on real map, colored by R.

Outputs:
  <stem>_map.html   - interactive map (GPS curvature colored track on OSM tiles)
  <stem>_plot.png   - 3-panel chart: radius over time, speed by direction, track scatter
"""

import argparse
import csv
import math
import sys
import webbrowser

import folium
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np


def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "t":       float(r["t"]),
                "lat":     float(r["lat"]),
                "lon":     float(r["lon"]),
                "speed":   float(r["speed_kmh"]),
                "R":       float(r["R_gps"]) if r["R_gps"] else math.inf,
                "dir":     r["dir_gps"],
                "R_osm":   float(r["R_osm"]) if r["R_osm"] else math.inf,
                "dir_osm": r["dir_osm"],
                "road":    r.get("road_name", ""),
                "quality": r["quality"],
            })
    return rows


def _r_to_rgb(R, vmin=10, vmax=500):
    """red (tight) -> yellow -> green (straight)"""
    if R == math.inf or R > vmax:
        return (46, 204, 113)
    t = (math.log(max(R, vmin)) - math.log(vmin)) / (math.log(vmax) - math.log(vmin))
    t = max(0.0, min(1.0, t))
    return (int(255 * (1 - t)), int(200 * t), 0)


def rgb_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)



def build_map(rows, out_path):
    lats = [r["lat"] for r in rows]
    lons = [r["lon"] for r in rows]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)]

    m = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap")

    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        R = a["R"]
        color = rgb_hex(_r_to_rgb(R))
        r_label = f"{R:.0f} m" if R != math.inf else "straight"
        tip = f"t={a['t']:.1f}s | {a['speed']:.1f} km/h | R={r_label} | {a['dir']}"
        if a.get("road"):
            tip += f" | {a['road']}"
        folium.PolyLine(
            [(a["lat"], a["lon"]), (b["lat"], b["lon"])],
            color=color, weight=5, opacity=0.9,
            tooltip=folium.Tooltip(tip, sticky=False),
        ).add_to(m)

    folium.Marker([rows[0]["lat"], rows[0]["lon"]], tooltip="START",
                  icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker([rows[-1]["lat"], rows[-1]["lon"]], tooltip="END",
                  icon=folium.Icon(color="blue", icon="stop")).add_to(m)

    curves = [r for r in rows if r["R"] != math.inf]
    if curves:
        t = min(curves, key=lambda r: r["R"])
        folium.Marker(
            [t["lat"], t["lon"]],
            tooltip=f"Tightest: R={t['R']:.1f} m ({t['dir']}) at t={t['t']:.1f}s",
            icon=folium.Icon(color="red", icon="exclamation-sign"),
        ).add_to(m)

    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;background:white;
                padding:12px 16px;border:1px solid #aaa;border-radius:6px;
                font-size:13px;line-height:1.8">
      <b>GPS Curvature radius R</b><br>
      <span style="color:#ff0000">&#9644;</span> &lt; 50 m - tight curve<br>
      <span style="color:#ff8800">&#9644;</span> 50-200 m - moderate<br>
      <span style="color:#c8c800">&#9644;</span> 200-500 m - gentle<br>
      <span style="color:#2ecc71">&#9644;</span> &gt; 500 m - straight<br>
      <br>Hover on track for details.
    </div>"""
    m.get_root().html.add_child(folium.Element(legend_html))

    m.save(out_path)
    print(f"Map saved: {out_path}")



def build_plot(rows, out_path):
    t   = np.array([r["t"]     for r in rows])
    R   = np.array([r["R"]     for r in rows])
    spd = np.array([r["speed"] for r in rows])
    lat = np.array([r["lat"]   for r in rows])
    lon = np.array([r["lon"]   for r in rows])

    curve_mask = R != math.inf
    R_plot = np.where(curve_mask, R, np.nan)

    fig, axes = plt.subplots(3, 1, figsize=(14, 11))
    fig.suptitle("Curvature Validation", fontsize=14, fontweight="bold")

    ax = axes[0]
    ax.semilogy(t, R_plot, color="black", lw=1)
    ax.axhline(1500, color="grey", lw=0.8, ls="--", label="straight threshold (1500 m)")
    ax.set_ylabel("Radius R (m, log)")
    ax.set_xlabel("Time (s)")
    ax.set_title("Curve radius over time  -  dips = turns")
    ax.legend(fontsize=8)
    ax.grid(True, which="both", alpha=0.3)

    ax = axes[1]
    for direction, color in {"left": "blue", "right": "red", "straight": "#bbbbbb"}.items():
        mask = np.array([r["dir"] == direction for r in rows])
        if mask.any():
            ax.scatter(t[mask], spd[mask], c=color, s=5, label=direction, alpha=0.8)
    ax.set_ylabel("Speed (km/h)")
    ax.set_xlabel("Time (s)")
    ax.set_title("Speed by turn direction  -  speed should drop in curves")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    ax.scatter(lon[~curve_mask], lat[~curve_mask], c="lightgrey", s=3, label="straight", zorder=1)
    if curve_mask.any():
        rv = R_plot[curve_mask]
        norm = mcolors.LogNorm(vmin=max(rv.min(), 5), vmax=1500)
        sc = ax.scatter(lon[curve_mask], lat[curve_mask],
                        c=rv, cmap="RdYlGn", norm=norm, s=15, zorder=2)
        plt.colorbar(sc, ax=ax, label="R (m)  red=tight  green=gentle")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("GPS track colored by curvature  -  red dots = tight curves")
    ax.set_aspect("equal")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"Plot saved: {out_path}")

    n = len(rows)
    nc = int(curve_mask.sum())
    print("\n--- Sanity check ---")
    print(f"Samples : {n}   In-curve : {nc} ({100*nc/n:.1f}%)")
    if nc:
        rv = R_plot[curve_mask]
        print(f"R  min / median : {rv.min():.1f} m / {np.median(rv):.1f} m")
        sc_mean = spd[curve_mask].mean()
        ss_mean = spd[~curve_mask].mean() if (~curve_mask).any() else float("nan")
        ratio = sc_mean / ss_mean if ss_mean > 0 else float("nan")
        verdict = "OK" if ratio < 0.95 else "CHECK"
        print(f"Speed curves / straights : {sc_mean:.1f} / {ss_mean:.1f} km/h  [{verdict}]")
    osm_ok = sum(1 for r in rows if r["R_osm"] != math.inf)
    print(f"OSM curves matched : {osm_ok}/{n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="*_curvature.csv from run_curvature.py")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    rows = load_csv(args.csv)
    if not rows:
        sys.exit("CSV is empty.")

    stem = args.csv.replace("_curvature.csv", "")
    build_map(rows, stem + "_map.html")
    build_plot(rows, stem + "_plot.png")

    if not args.no_browser:
        webbrowser.open(stem + "_map.html")


if __name__ == "__main__":
    main()
