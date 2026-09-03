# Wire Protocol

Both channels between the base station and the camera Pi run over plain UDP
on the shared Wi-Fi AP network (see the main README for the network setup).
There is no encryption, authentication, or delivery guarantee on either
channel — see [Security notes](#security-notes).

| Channel | Direction | Port | Transport | Purpose |
|---|---|---|---|---|
| Control | Base station → Camera Pi | `5005` (`CONTROL_PORT`) | UDP, plaintext | Pan/tilt velocity commands |
| Video | Camera Pi → Base station | `5000` (`VIDEO_PORT`) | UDP, length-prefixed chunks | Live H.264 video |
| Manual override | Base station ⇄ browser/client | `8081` | WebSocket | Relays arbitrary text straight to the control channel |
| Web UI | Base station | `8080` | HTTP | Flask app: `/`, `/remote_feed`, `/gaze_feed` |

## Control channel (`:5005`)

A single UDP datagram per command, plaintext, comma-separated:

```
"<x>,<y>"
```

- `x`, `y` are integers.
- Sent by `servo_driver` on the base station roughly every `TICK_S` seconds
  (20 Hz by default), computed as `gaze_offset * MAX_STEP` after the deadzone
  is applied.
- The camera Pi's `control_listener` parses this with
  `map(int, data.decode().split(","))` — a malformed packet is silently
  dropped (`except: pass`).
- **This is a velocity/delta signal, not an absolute angle.** The camera Pi
  integrates it over time (see `servo_loop` in
  [`architecture.md`](./architecture.md)) rather than jumping directly to
  `(x, y)` degrees.
- The same channel is used by the WebSocket manual-override relay — from the
  camera Pi's point of view, a manual command and a gaze-derived command are
  indistinguishable; both are just `"x,y"` datagrams on port 5005.

## Video channel (`:5000`)

Because UDP has no concept of message boundaries, the sender manually frames
each encoded video frame so the receiver can reassemble it:

**On the camera Pi (`UDPOutput.outputframe`):**
1. Prefix the raw H.264 frame `data` with its length as a 4-byte big-endian
   integer: `packet = len(data).to_bytes(4, 'big') + data`.
2. Split `packet` into `CHUNK_SIZE` (1400 byte) pieces and send each as its
   own UDP datagram to `(SERVER_IP, VIDEO_PORT)`.

**On the base station (`video_receiver`):**
1. Append every incoming datagram to a running byte buffer.
2. While the buffer holds at least 4 bytes, read the first 4 bytes as the
   big-endian frame length `flen`.
3. If the buffer doesn't yet hold `4 + flen` bytes, stop and wait for more
   packets.
4. Otherwise, slice out the `flen`-byte frame, feed it to the PyAV H.264
   decoder, and drop the consumed bytes from the buffer.
5. Each decoded frame is re-encoded as a JPEG (quality 70) and stored as
   `latest_remote_jpeg` for the `/remote_feed` MJPEG stream.

**Why 1400 bytes per chunk?** It comfortably fits under the ~1500-byte
Ethernet/Wi-Fi MTU once UDP/IP headers are subtracted, avoiding IP-level
fragmentation.

**Loss behavior:** there is no retransmission or forward error correction. A
dropped chunk corrupts the frame it belongs to; `video_receiver` has no way
to detect this mid-frame, so a lost chunk can desynchronize the buffer until
the decoder or the next valid length prefix recovers. In practice this shows
up as an occasional dropped or glitched frame rather than a stalled stream.

## Coordinate & value conventions

| Value | Range | Meaning |
|---|---|---|
| `gaze_offset[0]`, `gaze_offset[1]` (base station) | `-0.5` to `+0.5` | Horizontal/vertical gaze position relative to center; `0` = looking straight at the webcam |
| `pan`, `tilt` (both devices) | `0°` to `180°` | Absolute servo angle; `90°` is center on both axes |
| Control datagram `x`, `y` | integer, roughly `-MAX_STEP` to `+MAX_STEP` | Requested pan/tilt delta for this tick, before the camera Pi's own smoothing |

## Security notes

- Neither channel is encrypted or authenticated beyond the Wi-Fi AP's WPA2
  passphrase — anything already on `Pi_Network` can send control commands or
  inject video.
- There's no sequence numbering or replay protection on the control channel.
- This protocol is designed for a small, trusted local network (per the
  project's scope), not for use over the open internet.
