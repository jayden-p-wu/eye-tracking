# Hardware Setup

## Parts list

**Base station**
- Raspberry Pi 5
- USB webcam (any UVC-compatible camera works with OpenCV)
- Wi-Fi interface capable of running an access point (the Pi 5's onboard
  Wi-Fi supports this; see the README's [Wi-Fi access point setup](../README.md#wi-fi-access-point-setup-on-the-pi-5))
- Power supply for the Pi 5

**Camera unit**
- A second Raspberry Pi with a `Picamera2`-compatible camera module
- A pan/tilt servo bracket
- Two standard hobby servos (pan + tilt)
- A servo HAT compatible with `pi_servo_hat` (e.g. a PCA9685-based HAT)
- Power supply for the Pi and, if the HAT doesn't share the Pi's rail, a
  separate supply for the servos (see [Power](#power) below)

## Assembly

1. Mount the camera module to the pan/tilt bracket so its cable has enough
   slack to move through the full range of motion without straining.
2. Attach the pan servo to the bracket's base (rotates left/right) and the
   tilt servo to the bracket's camera mount (rotates up/down).
3. Connect the pan servo to **channel 0** and the tilt servo to **channel 1**
   on the servo HAT — the code assumes this mapping:
   ```python
   hat.move_servo_position(0, int(pan), 180)
   hat.move_servo_position(1, int(tilt), 180)
   ```
   If your servos are wired to different channels, update those channel
   numbers in `client.py` to match.
4. Seat the servo HAT on the camera Pi's GPIO header.
5. Attach the camera module's ribbon cable to the Pi's camera connector.

## Power

Servos can draw significant current under load, especially at startup or
when stalled against a hard limit — enough to brown out a Pi sharing the same
5V rail. If you see the camera Pi randomly rebooting or the video feed
dropping out when the servos move:

- Power the servos from a separate 5V/6V supply rated for at least the
  combined stall current of both servos, with a common ground back to the
  Pi/HAT.
- Add a physical stop or software clamp (already present in `client.py` as
  `pan = max(0, min(180, pan))`) so the servos can't drive themselves against
  a mechanical limit continuously.

## Centering before first run

Both `server.py` and `client.py` assume `pan = tilt = 90°` (center) on
startup. Before powering on, manually rotate the pan/tilt bracket roughly to
its center position so the first servo command doesn't cause a large, sudden
jump.

## Network

Both devices need to be on the same Wi-Fi network — specifically, the
network the base station Pi 5 hosts itself. Set that up first; see the
[Wi-Fi access point setup](../README.md#wi-fi-access-point-setup-on-the-pi-5)
section of the main README before running either script.
