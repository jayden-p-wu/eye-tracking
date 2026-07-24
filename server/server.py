#!/usr/bin/env python3
import socket
import threading
import time
import asyncio
import websockets
import av
import cv2
import numpy as np
from collections import deque
from flask import Flask, Response
import dlib

# CONFIG
VIDEO_PORT = 5000
CONTROL_PORT = 5005
CLIENT_IP = "192.168.4.2"

PREDICTOR_PATH = "shape_predictor_68_face_landmarks.dat"

SMOOTH_LEN = 6     # gaze smoothing frames
TICK_S = 0.05  # servo update interval (20Hz)
MAX_STEP = 8.0   # max degrees/tick at full gaze deflection
DEADZONE = 0.08  # gaze ratio distance from center ignored (0.0-0.5)

# SOCKETS
video_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
video_sock.bind(("0.0.0.0", VIDEO_PORT))
video_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
control_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# SHARED STATE
latest_remote_jpeg = None
latest_gaze_jpeg = None
remote_lock = threading.Lock()
gaze_lock = threading.Lock()

# Gaze offset from center (-0.5 to 0.5 each axis), shared between threads
gaze_offset = [0.0, 0.0]
gaze_offset_lock = threading.Lock()

# PI CAMERA RECEIVER
def video_receiver():
    global latest_remote_jpeg
    codec = av.CodecContext.create('h264', 'r')
    buf = b''
    while True:
        try:
            buf += video_sock.recvfrom(65536)[0]
            while len(buf) >= 4:
                flen = int.from_bytes(buf[:4], 'big')
                if len(buf) < 4 + flen:
                    break
                data = buf[4:4 + flen]
                buf  = buf[4 + flen:]
                for pkt in codec.parse(data):
                    for frame in codec.decode(pkt):
                        img = frame.to_ndarray(format='bgr24')
                        ok, jpg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        if ok:
                            with remote_lock:
                                latest_remote_jpeg = jpg.tobytes()
        except Exception:
            buf = b''

# SERVO DRIVER
# Runs on fixed tick. Reads gaze_offset, moves pan/tilt proportionally.
def servo_driver():
    pan, tilt = 90.0, 90.0
    while True:
        time.sleep(TICK_S)
        with gaze_offset_lock:
            dx, dy = gaze_offset  # each -0.5 to +0.5

        # apply deadzone
        if abs(dx) < DEADZONE: dx = 0.0
        if abs(dy) < DEADZONE: dy = 0.0

        if dx == 0.0 and dy == 0.0:
            continue

        # velocity proportional to deflection magnitude
        pan += dx * MAX_STEP
        tilt += dy * MAX_STEP
        pan = max(0, min(180, pan))
        tilt = max(0, min(180, tilt))

        control_sock.sendto(
            f"{int(pan)},{int(tilt)}".encode(),
            (CLIENT_IP, CONTROL_PORT)
        )

# GAZE TRACKER
def find_pupil(gray, eye_pts):
    x, y, w, h = cv2.boundingRect(eye_pts)
    pad = 4
    x1, y1 = max(0, x-pad), max(0, y-pad)
    roi = gray[y1:y+h+pad, x1:x+w+pad]
    if roi.size == 0:
        return None, None
    blurred = cv2.GaussianBlur(roi, (7, 7), 0)
    inv = cv2.bitwise_not(blurred)
    _, _, _, loc = cv2.minMaxLoc(inv)
    return x1 + loc[0], y1 + loc[1]

def gaze_loop():
    global latest_gaze_jpeg

    detector = dlib.get_frontal_face_detector()
    predictor = dlib.shape_predictor(PREDICTOR_PATH)
    LEFT_EYE = list(range(36, 42))
    RIGHT_EYE = list(range(42, 48))

    webcam = cv2.VideoCapture(0)
    smooth_h = deque(maxlen=SMOOTH_LEN)
    smooth_v = deque(maxlen=SMOOTH_LEN)

    print("Gaze tracker running.")

    while True:
        ok, frame = webcam.read()
        if not ok:
            time.sleep(0.05)
            continue

        fh, fw = frame.shape[:2]
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector(gray, 0)

        if len(faces) > 0:
            shape = predictor(gray, faces[0])
            left_pts  = np.array([(shape.part(i).x, shape.part(i).y) for i in LEFT_EYE])
            right_pts = np.array([(shape.part(i).x, shape.part(i).y) for i in RIGHT_EYE])

            lx, ly = find_pupil(gray, left_pts)
            rx, ry = find_pupil(gray, right_pts)

            if lx and rx:
                # normalize pupil positions to 0-1 within each eye bounding box
                def ratio(pts, px, py):
                    x, y, w, h = cv2.boundingRect(pts)
                    return (px - x) / max(w, 1), (py - y) / max(h, 1)

                lh, lv = ratio(left_pts,  lx, ly)
                rh, rv = ratio(right_pts, rx, ry)

                smooth_h.append((lh + rh) / 2)
                smooth_v.append((lv + rv) / 2)

                avg_h = np.mean(smooth_h)  # 0=left, 1=right
                avg_v = np.mean(smooth_v)  # 0=up,   1=down

                # offset from center: -0.5 to +0.5
                with gaze_offset_lock:
                    gaze_offset[0] = avg_h - 0.5
                    gaze_offset[1] = avg_v - 0.5

                # annotate frame
                cv2.polylines(frame, [left_pts],  True, (0, 255, 0), 1)
                cv2.polylines(frame, [right_pts], True, (0, 255, 0), 1)
                cv2.circle(frame, (lx, ly), 3, (0, 0, 255), -1)
                cv2.circle(frame, (rx, ry), 3, (0, 0, 255), -1)
                dx, dy = gaze_offset
                cv2.putText(frame, f"dx={dx:+.2f} dy={dy:+.2f}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        else:
            with gaze_offset_lock:
                gaze_offset[0] = 0.0
                gaze_offset[1] = 0.0
            cv2.putText(frame, "No face", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        _, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        with gaze_lock:
            latest_gaze_jpeg = jpg.tobytes()

    webcam.release()

# FLASK
app = Flask(__name__)

def _stream(get_frame, lock):
    last = None
    while True:
        with lock:
            frame = get_frame()
        if frame is None or frame is last:
            time.sleep(0.005)
            continue
        last = frame
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'

@app.route('/remote_feed')
def remote_feed():
    return Response(_stream(lambda: latest_remote_jpeg, remote_lock),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/gaze_feed')
def gaze_feed():
    return Response(_stream(lambda: latest_gaze_jpeg, gaze_lock),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return r"""<!DOCTYPE html>
<html><head><title>Gaze Camera Control</title><style>
body{background:#111;color:#eee;font-family:sans-serif;text-align:center;padding:20px;margin:0}
h1{font-size:1.1em;color:#aaa;margin-bottom:12px}
.feeds{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}
.feed-box{display:flex;flex-direction:column;align-items:center;gap:6px}
.label{font-size:11px;color:#666;text-transform:uppercase;letter-spacing:1px}
img{border:2px solid #333}
</style></head><body>
<h1>Gaze-Controlled Camera</h1>
<div class="feeds">
  <div class="feed-box"><div class="label">Pi Camera</div><img src="/remote_feed" width="560"></div>
  <div class="feed-box"><div class="label">Gaze Debug</div><img src="/gaze_feed" width="420"></div>
</div>
</body></html>"""

# WEBSOCKET RELAY
async def ws_handler(ws):
    async for msg in ws:
        try: control_sock.sendto(msg.encode(), (CLIENT_IP, CONTROL_PORT))
        except: pass

def run_ws():
    async def main():
        async with websockets.serve(ws_handler, "0.0.0.0", 8081):
            await asyncio.Future()
    asyncio.run(main())

if __name__ == "__main__":
    threading.Thread(target=video_receiver, daemon=True).start()
    threading.Thread(target=servo_driver, daemon=True).start()
    threading.Thread(target=run_ws, daemon=True).start()
    threading.Thread(target=gaze_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, threaded=True)
