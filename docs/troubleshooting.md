# Troubleshooting

## Base station won't start / crashes on launch

**`FileNotFoundError` or dlib error mentioning the predictor file**
`PREDICTOR_PATH` points to `shape_predictor_68_face_landmarks.dat`, which
isn't included in the repo. Download and extract it next to `server.py`:
```
wget http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2
bunzip2 shape_predictor_68_face_landmarks.dat.bz2
```

**Webcam won't open (`cv2.VideoCapture(0)` fails or returns blank frames)**
- Confirm another application isn't already holding the webcam.
- Try a different index (`cv2.VideoCapture(1)`, etc.) if multiple video
  devices are present.
- On Linux, check the device exists: `ls /dev/video*`.

## "No face" shown constantly on the gaze debug feed

- Check lighting — see [tuning.md](./tuning.md#gaze-detection-quality-not-a-constant-but-worth-tuning).
- Make sure you're within the webcam's field of view and roughly facing it.
- Confirm `shape_predictor_68_face_landmarks.dat` loaded correctly (a
  corrupted/partial download will still load without erroring in some dlib
  versions, but detection quality will suffer).

## Camera doesn't move at all

1. **Confirm the control channel is actually connecting.** On the camera Pi,
   check that `control_listener` is receiving packets — a quick check is
   `sudo tcpdump -i wlan0 udp port 5005` while looking away from center on
   the base station.
2. **Check `CLIENT_IP` on the base station matches the camera Pi's actual
   address** on `Pi_Network` (`192.168.4.1x`), and `SERVER_IP` on the camera
   Pi is `192.168.4.1`. A mismatch here means commands go nowhere.
3. **Check the servo HAT is seated correctly and powered** — see
   [hardware-setup.md](./hardware-setup.md#power). A HAT that's browning out
   under load can appear to "not respond" rather than erroring loudly.
4. **Check you're inside the deadzone.** If you're looking almost exactly at
   center, `DEADZONE` (default `0.08`) intentionally suppresses movement —
   look further off-center to test.

## Camera moves erratically / jitters constantly

This is almost always a tuning issue, not a wiring issue — see
[tuning.md](./tuning.md) for the full guide. Quick fixes:
- Increase `DEADZONE` on the base station.
- Decrease `alpha` on the camera Pi (smooths velocity more).
- Improve lighting to reduce noisy gaze estimates.

## No video in `/remote_feed`, but `/gaze_feed` works fine

`/gaze_feed` is entirely local to the base station, so it working confirms
the Flask app itself is fine — the problem is specific to the video pipeline
between the two Pis.

1. **Confirm the camera Pi is actually streaming.** Check `Picamera2`
   started without error and `UDPOutput` is being called (add a print
   statement in `outputframe` temporarily if needed).
2. **Check `VIDEO_PORT` (5000) isn't blocked.** Since both devices are on the
   Pi 5's own AP, there shouldn't be a firewall in the way by default, but
   confirm nothing (e.g. `ufw`) is filtering UDP on that port on the base
   station.
3. **Check the receive buffer isn't overflowing.** `server.py` sets
   `SO_RCVBUF` to 2 MB; on a very congested Wi-Fi link this can still be
   insufficient. Consecutive dropped chunks can desync the frame-length
   parsing in `video_receiver` — a symptom of this is the feed looking
   glitched/corrupted rather than simply absent.

## Video is present but very laggy

- Lower `bitrate` in `H264Encoder(bitrate=1_500_000)` on the camera Pi if
  Wi-Fi throughput is the bottleneck.
- Confirm nothing else is using significant bandwidth on `Pi_Network`.
- Video decode (PyAV) and JPEG re-encoding both run on the base station's
  main video thread — if the Pi 5 is CPU-constrained (e.g. also running the
  gaze detector at a high frame rate), video latency will suffer. Check CPU
  usage (`htop`) on the base station while streaming.

## Wi-Fi access point isn't showing up on the camera Pi

Walk back through the [Wi-Fi access point setup](../README.md#wi-fi-access-point-setup-on-the-pi-5)
steps in order and re-verify each one, especially:
```
iw dev
```
should show `wlan0_ap` with `type AP`. If it doesn't, `hostapd` likely
failed to start — check `sudo systemctl status hostapd` and
`journalctl -u hostapd` for the actual error (a common cause is another
process, like `wpa_supplicant`, already holding the wireless interface).
