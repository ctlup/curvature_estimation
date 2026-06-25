# Dashcam Embedded Metadata — Full Reference

**Device:** Nextbase 622GW  
**Source tool:** ExifTool 13.59, flags `-ee -G3`  
**Sample file:** `240829_101922_001_FH.MP4` (180 s clip, 2024-08-29)

---

## Device and Firmware

| Field | Value |
|---|---|
| Model | Nextbase 622GW |
| Firmware version | NBDVR622GWA-R11.1 |
| FCC-ID | 2AOT9-NBDVR622GW |
| Serial number | 224201068 |
| RTOS build | 38c09bd2 |
| Linux build | 5d771310 |
| NBCD | 04.1 |
| Alexa module | 01.7 |
| Second camera | NC (not connected) |
| Battery at record | Full |

---

## Recording Settings

| Field | Value |
|---|---|
| Resolution | 1920 × 1080 @ 29.97 fps |
| Video codec | H.264 / AVC (Ambarella encoder) |
| Average bitrate | 13.1 Mbps |
| Audio | Off |
| Loop length | 3 Min |
| Dual files | On (low-res copy alongside main) |
| Image stabilisation | Off |
| G-sensor sensitivity | Medium |
| Speed units | KMH |
| GPS stamp overlay | On |
| Speed stamp overlay | On |
| Time lapse | Off |
| Parking mode | Off |
| Emergency SOS | Off |

---

## File Container

| Field | Value |
|---|---|
| Container format | MP4 / ISO 14496-12:2005 (AVC ext) |
| Compatible brands | avc1, isom |
| File size | 315 MB |
| Media data size | 294,691,012 bytes |
| Duration | 0:03:00 (180 s) |
| Create date | 2024-08-29 10:19:12 |
| Time scale | 30,000 ticks/s |

### Tracks

| Track | Type | Details |
|---|---|---|
| 1 | Video | H.264, 1920×1080, 29.97 fps, 24-bit colour |
| 2 | Audio | AAC-LC, 2ch, 16 kHz, 16-bit — muted (Audio = Off) |
| 3 | Telemetry | text/Ambarella EXT, 1 kHz — GPS + IMU stream |

---

## SD Card

| Field | Value |
|---|---|
| Type | SDXC |
| Class | Class 10 |
| File system | exFAT |
| Capacity | 238.7 GB |
| Manufacturer | Samsung (ID 0x1B) |
| OEM ID | SM (0x534d) |
| Model | EE4S5 |
| Serial number | 2bea672c |
| Manufacture date | August 2023 |

---

## GPS Telemetry — Per-Sample Fields

The dashcam writes one telemetry block (one ExifTool `Doc`) every **0.1 seconds** into Track 3. Each block contains:

| Field | Unit | Example (t = 0 s) |
|---|---|---|
| `GPSDateTime` | UTC, 0.1 s resolution | 2024:08:29 08:18:44.600Z |
| `GPSLatitude` | DMS → decimal degrees | 43 deg 32' 3.39" N → 43.534275 |
| `GPSLongitude` | DMS → decimal degrees | 13 deg 30' 1.05" E → 13.500292 |
| `GPSAltitude` | metres above mean sea level | 36.2 m |
| `GPSSpeed` | km/h | 32.79 |
| `GPSTrack` | compass bearing 0–360° | 222.02 |
| `GPSSatellites` | count | 14 |
| `GPSDilutionOfPrecision` | dimensionless (lower = better) | 0.69 |
| `SampleTime` | seconds from clip start | 0.00, 0.10, 0.20 … |
| `SampleDuration` | seconds | 0.10 |

**First GPS fix — Clip 1:**

```
Position   : 43.534275 N, 13.500292 E  (near Osimo, Marche, Italy)
Altitude   : 36.2 m
Speed      : 32.8 km/h
Bearing    : 222° (south-southwest)
Satellites : 14
DOP        : 0.69  (excellent)
UTC time   : 2024-08-29 08:18:44.6Z  (local 10:18:44 CEST)
```

Total blocks per 180 s clip: ~1,800

---

## Accelerometer Data — Format

Each `AccelerometerData` field is a space-separated list of signed integers.  
The dashcam records **10 IMU readings per 0.1 s block** (100 Hz effective rate).  
Each reading is a group of 6 values:

```
[ gyro_x, gyro_y, gyro_z, acc_x, acc_y, acc_z ]
  pos 0    pos 1   pos 2   pos 3  pos 4  pos 5
```

**Axis mapping** (dashcam mounted on windshield, facing forward):

| Position | Sensor | Physical axis | At rest |
|---|---|---|---|
| 0 | gyro_x | angular rate X | ~0 |
| 1 | gyro_y | angular rate Y | ~0 |
| 2 | gyro_z | angular rate Z | ~0 |
| 3 | acc_x | linear — **vertical** | ≈ +2048 counts (+1 g) |
| 4 | acc_y | linear — **lateral** | ≈ 0 |
| 5 | acc_z | linear — **longitudinal** | ≈ 0 |

**Scale factor:** `2048 raw counts = 1 g`

Conversion:
```
g = raw_count / 2048
```

**Verification:** acc_x mean across all static samples = 2038 counts = 0.978 g, within 2.2% of the theoretical 1 g. Scale factor confirmed.

**Example** — Doc1, first 6-value group: `... 2090  -386  314 ...` (positions 3, 4, 5)

```
acc_x = 2090 / 2048 = +1.020 g   (vertical — gravity, vehicle nearly stopped)
acc_y = -386 / 2048 = -0.188 g   (lateral)
acc_z =  314 / 2048 = +0.153 g   (longitudinal)
```

Each 0.1 s block contains 10 readings × 6 integers = **60 integers** in `AccelerometerData`.

---

## Device Locale Settings

| Field | Value |
|---|---|
| Language | Italian |
| Country | Other |
| Time zone (DST offset) | +1 |
| Alexa wake word language | Italian |
| Speed units | KMH |

---

## Network Credentials Warning

The MP4 container header stores the dashcam Wi-Fi credentials in **plaintext**. ExifTool exposes them with no special flag. Anyone who runs `exiftool` on a shared MP4 file can read the Wi-Fi SSID and password.

**Before publishing raw MP4 files publicly:** change the dashcam Wi-Fi password in the Nextbase app settings, or strip the metadata with `exiftool -overwrite_original -all= file.mp4` (this removes all embedded telemetry, so do it on a copy).

This project does not publish the raw MP4 files (they are in `.gitignore`). Only the extracted CSV and HTML outputs are committed.

---

## What Can Be Derived from This Metadata

| Derived quantity | Source fields |
|---|---|
| Road curvature radius R | `GPSSpeed` + rate of change of `GPSTrack` |
| Road slope / gradient | `GPSAltitude` differences ÷ Haversine ground distance |
| Lateral g-force (cornering) | acc_y / 2048 |
| Longitudinal g-force (braking/acceleration) | acc_z / 2048 |
| Vertical g-force (road roughness) | acc_x / 2048 |
| GPS fix quality | `GPSDilutionOfPrecision` + `GPSSatellites` |
| Exact UTC timing | `GPSDateTime` at 0.1 s resolution |
| Full route replay | `GPSLatitude` / `GPSLongitude` at 10 Hz |

See `enrich_telemetry.py` for the implementation and `README.md` for the full mathematical formulations.
