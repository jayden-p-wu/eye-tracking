# Tuning Guide

The default constants are a reasonable starting point, but the right values
depend on your webcam, lighting, servos, and how fast/smooth you want the
camera to move. This doc explains what each one does and which direction to
move it.

## Base station (`server.py`)

| Constant | Default | Effect of increasing it | Effect of decreasing it |
|---|---|---|---|
| `SMOOTH_LEN` | `6` | Smoother gaze estimate, but more lag between looking somewhere and the offset reflecting it | Faster to respond, but noisier — more likely to jitter |
| `TICK_S` | `0.05` (20 Hz) | Fewer, larger servo command updates per second | More frequent updates, more network traffic, marginally lower latency |
| `MAX_STEP` | `8.0` | Faster maximum camera movement per tick at full gaze deflection | Slower, gentler maximum movement |
| `DEADZONE` | `0.08` | Larger "looking at center" tolerance — less drift/jitter when roughly centered, but small intentional glances near center get ignored | Smaller tolerance — more responsive near center, but more prone to jitter from noise |

**If the camera drifts or twitches when you're looking roughly at the
center:** increase `DEADZONE` first, then `SMOOTH_LEN`.

**If the camera feels sluggish to respond to a deliberate glance:** decrease
`SMOOTH_LEN`, or increase `MAX_STEP` for a faster (but potentially less
precise) response.

## Camera Pi (`client.py`)

| Constant | Default | Effect of increasing it | Effect of decreasing it |
|---|---|---|---|
| `SPEED` | `90.0` | Faster overall servo motion for a given smoothed velocity | Slower, more controlled motion |
| `DT` | `0.02` (50 Hz) | Finer-grained motion integration; rarely needs changing | Coarser motion steps |
| `alpha` | `0.15` | Velocity commands take effect faster — more responsive but more jittery | Velocity commands are smoothed more heavily — smoother but laggier |

**`alpha` is the most impactful single value for perceived motion quality.**
The comment in the code (`0.1–0.3 good range`) is a reasonable place to
experiment: try `0.1` for very smooth (but slower-responding) motion, or
`0.3` if the camera feels too sluggish to follow deliberate gaze shifts.

## Gaze detection quality (not a constant, but worth tuning)

The pupil-finding heuristic (`find_pupil`) locates the darkest point in each
eye's bounding box after a Gaussian blur. It's sensitive to:

- **Lighting** — strong shadows or glare on the face create false "dark
  points" that aren't the pupil. Even, diffuse front lighting works best.
- **Webcam distance/angle** — the 68-point landmark model is more accurate
  face-on than at steep angles.
- **Glasses** — reflections on lenses can confuse the darkest-point heuristic;
  if this is a problem, try repositioning the light source rather than
  changing code.

If detection is unreliable, it's usually faster to fix the physical setup
(lighting, camera position) than to compensate for it in the smoothing
constants above.

## A practical tuning order

1. Get reliable face/eye detection first (see above) — no amount of
   smoothing fixes a bad gaze estimate.
2. Set `DEADZONE` so the camera holds still when you look near center.
3. Adjust `SMOOTH_LEN` and `alpha` together until motion feels smooth without
   feeling laggy — change one at a time.
4. Only then tune `MAX_STEP` / `SPEED` for how fast you want the camera to
   move at full deflection.
