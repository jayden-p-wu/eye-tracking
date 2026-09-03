# Architecture

This document goes deeper than the README into *why* the system is built the
way it is: the threading model on each device, how data flows between them,
and the reasoning behind the design choices.

## Two independent processes

The system is two standalone Python scripts that never share memory or a
process — only the network:

- **`server.py`** runs on the base station (Raspberry Pi 5).
- **`client.py`** runs on the camera Pi.

Each is internally multi-threaded so that a slow or blocking operation in one
thread (e.g. waiting on a face detector) never stalls another (e.g. sending
the next servo command on schedule).

## Base station (`server.py`) thread model

| Thread | Responsibility |
|---|---|
| `video_receiver` | Reads raw UDP packets from the camera Pi, reassembles length-prefixed H.264 frames, decodes them with PyAV, and re-encodes each as a JPEG stored in `latest_remote_jpeg`. |
| `gaze_loop` | Owns the local webcam. Runs face/eye detection every frame, estimates gaze offset, updates the shared `gaze_offset`, and writes an annotated debug JPEG to `latest_gaze_jpeg`. |
| `servo_driver` | Wakes up every `TICK_S` seconds, reads `gaze_offset`, applies the deadzone, and sends a `"pan,tilt"` UDP command to the camera Pi. |
| `run_ws` | Runs a WebSocket server (port 8081) that forwards any message it receives straight to the camera Pi's control port — a manual override path independent of gaze. |
| Flask (main thread) | Serves the web UI and the two MJPEG feeds (`/remote_feed`, `/gaze_feed`) on port 8080. |

Three plain `threading.Lock()`s (`remote_lock`, `gaze_lock`, `gaze_offset_lock`)
guard the values shared between these threads — each lock is held only long
enough to read or write a single variable, never across a blocking call.

**Why split gaze estimation from servo driving?** Face detection and pupil
localization take a variable amount of time per frame depending on lighting
and CPU load. If the servo commands were sent directly from inside that loop,
motion would inherit that jitter. Instead, `gaze_loop` only ever writes the
latest offset, and `servo_driver` reads it on a fixed, independent clock
(`TICK_S = 0.05s`, i.e. 20 Hz) — so servo motion stays smooth even if the
vision pipeline's frame rate isn't.

## Camera Pi (`client.py`) thread model

| Thread | Responsibility |
|---|---|
| `control_listener` | Blocks on a UDP socket bound to the control port, parses each `"x,y"` message, and updates shared velocity `vx, vy`. |
| `servo_loop` | Runs every `DT = 0.02s` (50 Hz). Exponentially smooths `(vx, vy)` into `(sx, sy)`, integrates that into absolute `pan`/`tilt` angles, clamps to `0–180°`, and writes them to the servo HAT. |
| Main thread | Configures and starts `Picamera2`, which encodes video with `H264Encoder` and pushes each encoded frame into a custom `UDPOutput` sink. |

**Why velocity-based control instead of sending absolute angles directly?**
The base station's gaze signal is noisy and only loosely tracks "where you're
looking," not "where the camera should point right now." Treating it as a
velocity (how fast to move, and in which direction) rather than a target
position means small, high-frequency fluctuations in the gaze estimate don't
translate into visible camera jitter — they get absorbed by the smoothing and
integration steps instead.

**Double smoothing.** The signal is smoothed twice, independently, for two
different kinds of noise:
1. On the base station, `gaze_loop` averages the last `SMOOTH_LEN` (6) frames
   of pupil-ratio estimates — this smooths out per-frame *vision* noise.
2. On the camera Pi, `servo_loop` exponentially smooths the incoming velocity
   commands with `alpha = 0.15` — this smooths out the coarser, lower-rate
   *command* signal so the physical servo motion doesn't step or jerk between
   consecutive UDP packets.

## Data flow

```
Webcam --(frames)--> gaze_loop --(gaze_offset, locked)--> servo_driver
                                                                 |
                                                    UDP :5005 "pan,tilt"
                                                                 v
                                                        control_listener
                                                                 |
                                                        (vx, vy, locked)
                                                                 v
                                                            servo_loop
                                                                 |
                                                     hat.move_servo_position()

Picamera2 --(H264 frames)--> UDPOutput --UDP :5000 (chunked)--> video_receiver
                                                                 |
                                                        PyAV decode + re-encode
                                                                 v
                                                          latest_remote_jpeg
                                                                 |
                                                    Flask /remote_feed (MJPEG)
```

The gaze debug view (`/gaze_feed`) follows a parallel, entirely local path:
`gaze_loop` annotates each webcam frame directly and stores it in
`latest_gaze_jpeg`, with no network hop involved.

## Why UDP, not TCP

Both the video and control channels use UDP rather than TCP:

- **Control commands** are only ever useful if they're current — a stale
  pan/tilt delta from half a second ago is worse than no command at all. TCP's
  retransmission and head-of-line blocking would delay newer commands behind
  older ones; UDP just drops what doesn't arrive, and the next tick's command
  supersedes it moments later anyway.
- **Video frames** are similarly latency-sensitive: a dropped or late frame is
  better skipped than blocking the stream to retransmit it. The custom framing
  (4-byte length prefix, `CHUNK_SIZE`-sized fragments) exists specifically
  because UDP has no built-in message boundaries or delivery guarantees — see
  [`protocol.md`](./protocol.md) for the exact wire format.

## Why the base station hosts its own Wi-Fi AP

Running `hostapd`/`dnsmasq` on the Pi 5 (see the main README) means the two
devices form a self-contained network with a fixed, predictable IP scheme
(`192.168.4.1` for the base station, `192.168.4.10–.50` for anything that
joins). That removes any dependency on a home router, makes the system usable
in the field, and keeps `SERVER_IP`/`CLIENT_IP` config values stable across
different networks.
