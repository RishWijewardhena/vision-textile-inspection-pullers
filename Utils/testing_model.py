#!/usr/bin/env python3
"""
Super Simple YOLO Mask Viewer - Just draws what the model detects
"""

import cv2
import numpy as np
from ultralytics import YOLO
import time
import os

# Config
MODEL_PATH = "New_pullers_model.pt"
CAMERA_INDEX = "/dev/video0"
CONFIDENCE = 0.2
MASK_ALPHA = 0.5

def main():
    print(f"Loading model: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)
    
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 960)
    
    if not cap.isOpened():
        print("ERROR: Cannot open camera!")
        return

    os.makedirs("test_outputs", exist_ok=True) # Create directory to save output images
    
    print("Ready! Press 'q' to quit")
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Run detection
        results = model(frame, conf=CONFIDENCE, verbose=False)
        
        # Draw all masks
        if results[0].masks is not None:
            masks = results[0].masks.data.cpu().numpy()
            
            for mask in masks:
                # Resize mask to frame size
                mask_resized = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
                mask_binary = (mask_resized > 0.5).astype(np.uint8)
                
                # Random color for this mask
                # color = np.random.randint(0, 255, 3).tolist()
                color=(0, 255, 0) # Green for all masks
                
                # Draw mask overlay
                colored_mask = np.zeros_like(frame)
                colored_mask[mask_binary == 1] = color
                frame = cv2.addWeighted(frame, 1.0, colored_mask, MASK_ALPHA, 0)
                
                # Draw contours around mask
                counter_color=(0,0,0) # Black contours
                contours, _ = cv2.findContours(mask_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(frame, contours, -1, counter_color, 2)
        
        # cv2.imshow('Masks', frame)
        cv2.putText(frame, f"Frame: {frame_count}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

        cv2.imwrite(f'test_outputs/test_output_{frame_count}.jpg', frame) # Save the output frame as an image
        frame_count += 1

        time.sleep(0.1) # Add a small delay to avoid overwhelming the system with too many frames
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# """
# Super Simple YOLO Mask Viewer - Just draws what the model detects
# """

# import cv2
# import numpy as np
# import threading
# import time
# from ultralytics import YOLO

# # Config
# MODEL_PATH = "New_pullers_model.pt"
# CAMERA_INDEX = "/dev/video0"
# CONFIDENCE = 0.2
# MASK_ALPHA = 0.5

# # Brightness config
# BRIGHTNESS_CHECK_INTERVAL = 5 
#  # 2 minutes in seconds
# BRIGHTNESS_TOO_HIGH       = 110   # Max acceptable brightness (0-255)
# BRIGHTNESS_TOO_LOW        = 20    # Min acceptable brightness (0-255)

# # Camera exposure controls (from v4l2-ctl)
# AUTO_EXPOSURE_MANUAL    = 1       # Manual mode
# AUTO_EXPOSURE_AUTO      = 3       # Aperture Priority Mode (default)
# EXPOSURE_MIN            = 50      # min from v4l2-ctl
# EXPOSURE_MAX            = 10000   # max from v4l2-ctl
# EXPOSURE_DEFAULT        = 120     # default from v4l2-ctl
# EXPOSURE_STEP           = 50      # How much to increase/decrease per adjustment


# class BrightnessMonitor(threading.Thread):
#     """Monitors frame brightness and adjusts camera exposure every 2 minutes."""

#     def __init__(self, cap):
#         super().__init__(daemon=True)
#         self.cap              = cap
#         self.current_exposure = EXPOSURE_DEFAULT
#         self.running          = True
#         self.latest_frame     = None
#         self.lock             = threading.Lock()

#         # Switch to manual exposure mode so we can control it
#         self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTO_EXPOSURE_MANUAL)
#         self.cap.set(cv2.CAP_PROP_EXPOSURE, self.current_exposure)
#         print(f"📷 Camera set to manual exposure: {self.current_exposure}")

#     def update_frame(self, frame):
#         """Called from main thread to share latest frame."""
#         with self.lock:
#             self.latest_frame = frame.copy()

#     def get_brightness(self, frame):
#         """Returns average brightness of frame (0-255)."""
#         gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
#         return float(np.mean(gray))

#     def adjust_exposure(self, brightness):
#         """Adjusts camera exposure based on brightness level."""
#         if brightness > BRIGHTNESS_TOO_HIGH:
#             # Too bright → reduce exposure time
#             new_exposure = max(self.current_exposure - EXPOSURE_STEP, EXPOSURE_MIN)
#             action = f"Too bright ({brightness:.1f}) → reducing exposure"
#         elif brightness < BRIGHTNESS_TOO_LOW:
#             # Too dark → increase exposure time
#             new_exposure = min(self.current_exposure + EXPOSURE_STEP, EXPOSURE_MAX)
#             action = f"Too dark ({brightness:.1f}) → increasing exposure"
#         else:
#             print(f"✅ Brightness OK: {brightness:.1f} | Exposure: {self.current_exposure}")
#             return

#         if new_exposure != self.current_exposure:
#             self.current_exposure = new_exposure
#             self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTO_EXPOSURE_MANUAL)
#             self.cap.set(cv2.CAP_PROP_EXPOSURE, self.current_exposure)
#             print(f"⚙️  {action} | New exposure: {self.current_exposure}")
#         else:
#             print(f"⚠️  {action} | Exposure already at limit: {self.current_exposure}")

#     def run(self):
#         print("🔆 Brightness monitor started (checks every 2 minutes)")
#         while self.running:
#             time.sleep(BRIGHTNESS_CHECK_INTERVAL)

#             with self.lock:
#                 frame = self.latest_frame

#             if frame is None:
#                 continue

#             brightness = self.get_brightness(frame)
#             print(f"\n🔍 Brightness check → {brightness:.1f}/255")
#             self.adjust_exposure(brightness)

#     def stop(self):
#         # Restore auto exposure on exit
#         self.running = False
#         self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTO_EXPOSURE_AUTO)
#         print("📷 Camera restored to auto exposure mode")


# def main():
#     print(f"Loading model: {MODEL_PATH}")
#     model = YOLO(MODEL_PATH)

#     cap = cv2.VideoCapture(CAMERA_INDEX)
#     cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
#     cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 960)

#     if not cap.isOpened():
#         print("ERROR: Cannot open camera!")
#         return

#     # Start brightness monitor thread
#     brightness_monitor = BrightnessMonitor(cap)
#     brightness_monitor.start()

#     print("Ready! Press 'q' to quit")

#     while True:
#         ret, frame = cap.read()
#         if not ret:
#             break

#         # Share frame with brightness monitor
#         brightness_monitor.update_frame(frame)

#         # Run detection
#         results = model(frame, conf=CONFIDENCE, verbose=False)

#         # Draw all masks
#         if results[0].masks is not None:
#             masks = results[0].masks.data.cpu().numpy()

#             for mask in masks:
#                 # Resize mask to frame size
#                 mask_resized = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
#                 mask_binary = (mask_resized > 0.5).astype(np.uint8)

#                 # Green for all masks
#                 color = (0, 255, 0)

#                 # Draw mask overlay
#                 colored_mask = np.zeros_like(frame)
#                 colored_mask[mask_binary == 1] = color
#                 frame = cv2.addWeighted(frame, 1.0, colored_mask, MASK_ALPHA, 0)

#                 # Draw contours around mask
#                 contours, _ = cv2.findContours(mask_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
#                 cv2.drawContours(frame, contours, -1, (0, 0, 0), 2)

#         # Show brightness and exposure on frame
#         gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
#         brightness = float(np.mean(gray))
#         cv2.putText(frame, f"Brightness: {brightness:.1f}/255 | Exposure: {brightness_monitor.current_exposure}",
#                     (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

#         cv2.imshow('Masks', frame)

#         if cv2.waitKey(1) & 0xFF == ord('q'):
#             break

#     brightness_monitor.stop()
#     cap.release()
#     cv2.destroyAllWindows()


# if __name__ == "__main__":
#     main()