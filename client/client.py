#!/usr/bin/env python3
import socket
import threading
import time
import pi_servo_hat
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import Output

SERVER_IP = "192.168.4.1"
VIDEO_PORT = 5000
CONTROL_PORT = 5005
CHUNK_SIZE = 1400

hat = pi_servo_hat.PiServoHat()
hat.restart()

# STATE
vx, vy = 0, 0
pan, tilt = 90.0, 90.0

lock = threading.Lock()

# CONTROL LISTENER
def control_listener():
    global vx, vy
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", CONTROL_PORT))

    while True:
        try:
            x, y = map(int, sock.recvfrom(1024)[0].decode().split(","))
            with lock:
                vx, vy = x, y
        except:
            pass

# MOTION LOOP
def servo_loop():
    global pan, tilt, vx, vy

    SPEED = 90.0   # base speed
    DT = 0.02

    # smoothed velocity (THIS is the key fix)
    sx, sy = 0.0, 0.0
    alpha = 0.15   # smoothing factor (0.1–0.3 good range)

    while True:
        time.sleep(DT)

        # smooth velocity input (removes jitter)
        sx += (vx - sx) * alpha
        sy += (vy - sy) * alpha

        # integrate motion
        pan += sx * SPEED * DT
        tilt += sy * SPEED * DT

        # clamp
        pan = max(0, min(180, pan))
        tilt = max(0, min(180, tilt))

        try:
            hat.move_servo_position(0, int(pan), 180)
            hat.move_servo_position(1, int(tilt), 180)
        except:
            pass

# VIDEO OUTPUT
class UDPOutput(Output):
    def __init__(self):
        super().__init__()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)

    def outputframe(self, data, keyframe=True, timestamp=None, packet=None, audio=None):
        packet = len(data).to_bytes(4, 'big') + data
        for i in range(0, len(packet), CHUNK_SIZE):
            self.sock.sendto(packet[i:i+CHUNK_SIZE], (SERVER_IP, VIDEO_PORT))

if __name__ == "__main__":
    threading.Thread(target=control_listener, daemon=True).start()
    threading.Thread(target=servo_loop, daemon=True).start()

    picam2 = Picamera2()
    picam2.configure(
        picam2.create_video_configuration(
            main={"size": (640, 480), "format": "YUV420"},
            controls={"FrameDurationLimits": (33333, 33333)}  # ~30fps
        )
    )

    picam2.start_recording(H264Encoder(bitrate=1500000), UDPOutput())

    while True:
        time.sleep(1)
