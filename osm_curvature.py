import math
import csv
import json
import os
from dataclasses import dataclass, asdict
from typing import Optional, List, Tuple

import numpy as np

R_EARTH = 6371000.0
STRAIGHT_THRESHOLD_M = 1500.0


@dataclass
class GPSSample:
    t: float
    lat: float
    lon: float
    speed_kmh: float = 0.0
    heading_deg: Optional[float] = None
    dop: Optional[float] = None
    sats: Optional[int] = None


@dataclass
class CurvatureRow:
    t: float
    lat: float
    lon: float
    speed_kmh: float
    R_gps: float
    dir_gps: str
    R_osm: float
    dir_osm: str
    road_name: str
    quality: str


def haversine(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R_EARTH * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def to_local_xy(latlon, ref_lat, ref_lon):
    lat_m = 111320.0
    lon_m = 111320.0 * math.cos(math.radians(ref_lat))
    return np.array([[(lon - ref_lon) * lon_m, (lat - ref_lat) * lat_m]
                     for lat, lon in latlon], dtype=float)


def circumradius(p1, p2, p3):
    (x1, y1), (x2, y2), (x3, y3) = p1, p2, p3
    a = math.hypot(x2 - x1, y2 - y1)
    b = math.hypot(x3 - x2, y3 - y2)
    c = math.hypot(x1 - x3, y1 - y3)
    signed_area = (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)) / 2.0
    area = abs(signed_area)
    if area < 1e-6:
        return float('inf'), 0.0
    R = (a * b * c) / (4.0 * area)
    return R, signed_area


def _classify(R, signed_area):
    if R == float('inf') or R > STRAIGHT_THRESHOLD_M:
        return float('inf'), "straight"
    if signed_area > 0:
        return R, "left"
    if signed_area < 0:
        return R, "right"
    return R, "straight"


def curvature_from_heading(samples: List[GPSSample]) -> List[Tuple[float, str]]:
    out = []
    n = len(samples)
    for i in range(n):
        i0 = max(0, i - 1)
        i1 = min(n - 1, i + 1)
        s0, s1 = samples[i0], samples[i1]
        if s0.heading_deg is None or s1.heading_deg is None or i1 == i0:
            out.append((float('inf'), "straight"))
            continue
        dh = (s1.heading_deg - s0.heading_deg + 180.0) % 360.0 - 180.0
        dt = s1.t - s0.t
        if dt <= 0:
            out.append((float('inf'), "straight"))
            continue
        omega = math.radians(dh) / dt
        v = samples[i].speed_kmh / 3.6
        if abs(omega) < 1e-4 or v < 0.5:
            out.append((float('inf'), "straight"))
            continue
        R = abs(v / omega)
        direction = "right" if dh > 0 else "left"
        if R > STRAIGHT_THRESHOLD_M:
            out.append((float('inf'), "straight"))
        else:
            out.append((R, direction))
    return out


def curvature_from_positions(samples: List[GPSSample]) -> List[Tuple[float, str]]:
    latlon = [(s.lat, s.lon) for s in samples]
    if len(latlon) < 3:
        return [(float('inf'), "straight")] * len(samples)
    xy = to_local_xy(latlon, samples[0].lat, samples[0].lon)
    if len(xy) >= 5:
        k = np.array([0.15, 0.2, 0.3, 0.2, 0.15])
        xs = np.convolve(xy[:, 0], k, mode='same')
        ys = np.convolve(xy[:, 1], k, mode='same')
        xy = np.column_stack([xs, ys])
    out = []
    n = len(xy)
    for i in range(n):
        if i == 0 or i == n - 1:
            out.append((float('inf'), "straight"))
            continue
        R, sa = circumradius(xy[i - 1], xy[i], xy[i + 1])
        out.append(_classify(R, sa))
    return out


class OSMGraph:
    def __init__(self, ways: List[dict]):
        self.ways = ways
        self._proj_ref = None
        self._xy_ways = None

    @classmethod
    def from_overpass(cls, samples, pad_m=150.0, cache_dir=None):
        lats = [s.lat for s in samples]
        lons = [s.lon for s in samples]
        south, north = min(lats), max(lats)
        west, east = min(lons), max(lons)
        dlat = pad_m / 111320.0
        dlon = pad_m / (111320.0 * math.cos(math.radians((south + north) / 2)))
        bbox = (south - dlat, west - dlon, north + dlat, east + dlon)

        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            key = "graph_{:.4f}_{:.4f}_{:.4f}_{:.4f}.json".format(*bbox)
            path = os.path.join(cache_dir, key)
            if os.path.exists(path):
                with open(path) as f:
                    return cls([{"name": w["name"],
                                 "pts": [tuple(p) for p in w["pts"]]}
                                for w in json.load(f)])

        ways = cls._download(bbox)
        if cache_dir:
            with open(path, "w") as f:
                json.dump([{"name": w["name"], "pts": [list(p) for p in w["pts"]]}
                           for w in ways], f)
        return cls(ways)

    @staticmethod
    def _download(bbox):
        import requests
        s, w, n, e = bbox
        q = ("[out:json][timeout:60];"
             'way["highway"~"motorway|trunk|primary|secondary|tertiary|'
             'unclassified|residential|service"]'
             "({s},{w},{n},{e});(._;>;);out;"
             ).format(s=s, w=w, n=n, e=e)
        hdrs = {"User-Agent": "curvature-extractor/1.0"}
        r = requests.get("https://overpass-api.de/api/interpreter",
                         params={"data": q}, headers=hdrs, timeout=90)
        r.raise_for_status()
        data = r.json()
        nodes = {el["id"]: (el["lat"], el["lon"])
                 for el in data["elements"] if el["type"] == "node"}
        ways = []
        for el in data["elements"]:
            if el["type"] != "way":
                continue
            pts = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
            if len(pts) >= 2:
                ways.append({"name": el.get("tags", {}).get("name", "unnamed"),
                             "pts": pts})
        return ways

    def _ensure_projection(self, ref_lat, ref_lon):
        if self._proj_ref == (round(ref_lat, 3), round(ref_lon, 3)):
            return
        self._proj_ref = (round(ref_lat, 3), round(ref_lon, 3))
        self._xy_ways = []
        for w in self.ways:
            xy = to_local_xy(w["pts"], ref_lat, ref_lon)
            self._xy_ways.append({"name": w["name"], "xy": xy, "pts": w["pts"]})

    def curvature_at(self, lat, lon, heading_deg=None, step_m=5.0):
        if not self.ways:
            return float('inf'), "straight", "no_osm_match"
        self._ensure_projection(lat, lon)
        px, py = 0.0, 0.0

        best = None
        for wi, w in enumerate(self._xy_ways):
            xy = w["xy"]
            for si in range(len(xy) - 1):
                ax, ay = xy[si]
                bx, by = xy[si + 1]
                dx, dy = bx - ax, by - ay
                seg_len2 = dx * dx + dy * dy
                if seg_len2 < 1e-9:
                    continue
                tparam = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
                cx, cy = ax + tparam * dx, ay + tparam * dy
                d = math.hypot(px - cx, py - cy)
                if best is None or d < best[0]:
                    best = (d, wi, si, (cx, cy))

        if best is None or best[0] > 40.0:
            return float('inf'), "straight", "no_osm_match"

        _, wi, si, proj = best
        way = self._xy_ways[wi]
        poly = self._resample(way["xy"], step_m)
        if len(poly) < 3:
            return float('inf'), "straight", way["name"]

        d2 = np.sum((poly - np.array(proj)) ** 2, axis=1)
        idx = int(np.argmin(d2))
        i0 = max(0, idx - 1)
        i2 = min(len(poly) - 1, idx + 1)
        if i2 - i0 < 2:
            if i0 == 0:
                i0, i1, i2 = 0, 1, 2
            else:
                i0, i1, i2 = len(poly) - 3, len(poly) - 2, len(poly) - 1
        else:
            i1 = idx
        R, sa = circumradius(tuple(poly[i0]), tuple(poly[i1]), tuple(poly[i2]))
        R, direction = _classify(R, sa)

        if direction != "straight" and heading_deg is not None:
            tangent = poly[i2] - poly[i0]
            way_bearing = math.degrees(math.atan2(tangent[0], tangent[1])) % 360.0
            diff = (way_bearing - heading_deg + 180.0) % 360.0 - 180.0
            if abs(diff) > 90.0:
                direction = "left" if direction == "right" else "right"
        return R, direction, way["name"]

    @staticmethod
    def _resample(xy, step_m):
        if len(xy) < 2:
            return xy
        seg = np.sqrt(np.sum(np.diff(xy, axis=0) ** 2, axis=1))
        s = np.concatenate([[0], np.cumsum(seg)])
        total = s[-1]
        if total < step_m:
            return xy
        targets = np.arange(0, total, step_m)
        rx = np.interp(targets, s, xy[:, 0])
        ry = np.interp(targets, s, xy[:, 1])
        return np.column_stack([rx, ry])


def process_trace(samples: List[GPSSample], use_osm=True, cache_dir=None,
                  dop_limit=5.0) -> List[CurvatureRow]:
    have_heading = sum(1 for s in samples if s.heading_deg is not None) > len(samples) // 2
    gps_curv = (curvature_from_heading(samples) if have_heading
                else curvature_from_positions(samples))

    graph = None
    if use_osm:
        try:
            graph = OSMGraph.from_overpass(samples, cache_dir=cache_dir)
        except Exception as e:
            print("OSM graph load failed ({}); R_osm will be inf".format(e))

    rows = []
    for i, s in enumerate(samples):
        Rg, dg = gps_curv[i]
        Ro, do, name = float('inf'), "straight", ""
        q = "ok"
        if s.dop is not None and s.dop > dop_limit:
            q = "low_gps"
        if graph is not None:
            Ro, do, name = graph.curvature_at(s.lat, s.lon, s.heading_deg)
            if name == "no_osm_match":
                q = "no_osm_match"
                name = ""
        rows.append(CurvatureRow(
            t=round(s.t, 3), lat=s.lat, lon=s.lon, speed_kmh=s.speed_kmh,
            R_gps=round(Rg, 1) if Rg != float('inf') else float('inf'),
            dir_gps=dg,
            R_osm=round(Ro, 1) if Ro != float('inf') else float('inf'),
            dir_osm=do, road_name=name, quality=q))
    return rows


def write_csv(rows: List[CurvatureRow], path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        w.writeheader()
        for r in rows:
            d = asdict(r)
            for k in ("R_gps", "R_osm"):
                if d[k] == float('inf'):
                    d[k] = ""
            w.writerow(d)


def samples_from_telemetry(telemetry) -> List[GPSSample]:
    return [GPSSample(t=s.t, lat=s.lat, lon=s.lon, speed_kmh=s.speed_kmh,
                      heading_deg=s.heading_deg, dop=s.dop, sats=s.sats)
            for s in telemetry]


def samples_from_source(source) -> List[GPSSample]:
    from metadata_extract import extract
    return samples_from_telemetry(extract(source))
