import serial.tools.list_ports
import cv2
import glob
import os
import re
import time


def find_esp32():
    for p in serial.tools.list_ports.comports():
        # Match by USB VID/PID
        if p.vid == 0x303A and p.pid == 0x1001:
            return p.device
    return None
            

def _camera_sort_key(path):
    match = re.search(r"(\d+)$", str(path))
    return int(match.group(1)) if match else 999


def camera_to_v4l2_index(camera):
    """Return an integer camera index for OpenCV's V4L2 backend."""
    if isinstance(camera, int):
        return camera

    camera = str(camera).strip()
    if camera.isdigit():
        return int(camera)

    match = re.fullmatch(r"/dev/video(\d+)", camera)
    if match:
        return int(match.group(1))

    return camera


def open_v4l2_camera(camera):
    """Open a camera with V4L2 using an integer index when possible."""
    camera_ref = camera_to_v4l2_index(camera)
    cap = cv2.VideoCapture(camera_ref, cv2.CAP_V4L2)
    if cap.isOpened():
        return cap

    cap.release()
    if camera_ref != camera:
        cap = cv2.VideoCapture(camera)
    return cap


def _camera_can_read(camera, attempts=5):
    cap = open_v4l2_camera(camera)
    try:
        if not cap.isOpened():
            return False

        for _ in range(attempts):
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                return True
            time.sleep(0.1)
        return False
    finally:
        cap.release()


def find_camera():
    configured_camera = os.getenv("CAMERA_DEVICE") or os.getenv("CAMERA_INDEX")
    detected_cameras = sorted(glob.glob("/dev/video*"), key=_camera_sort_key)
    cam_list = []

    if configured_camera:
        cam_list.append(configured_camera)
    cam_list.extend(detected_cameras)
    cam_list.extend(["/dev/video0", "/dev/video1", "/dev/video2"])

    seen = set()
    cam_list = [cam for cam in cam_list if not (cam in seen or seen.add(cam))]

    for cam in cam_list:
        if _camera_can_read(cam):
            return camera_to_v4l2_index(cam)

    return camera_to_v4l2_index(configured_camera or "/dev/video0")


if __name__ == "__main__":
    print(find_esp32())
    print(find_camera())
