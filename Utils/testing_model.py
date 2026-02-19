#!/usr/bin/env python3
"""
Simple YOLO Instance Segmentation Live Camera Feed
"""

import cv2
import numpy as np
from ultralytics import YOLO

# ============================================
# CONFIGURATION - EDIT THESE VALUES
# ============================================

MODEL_PATH = "yolov8s-seg.pt"  # Path to your .pt model file
CAMERA_INDEX = "/dev/video0"    # Camera device path
FRAME_WIDTH = 640               # Camera frame width
FRAME_HEIGHT = 480              # Camera frame height
CONFIDENCE = 0.25               # Detection confidence threshold (0.0 to 1.0)
IOU_THRESHOLD = 0.45            # IoU threshold for NMS
MASK_ALPHA = 0.4                # Transparency of segmentation masks (0.0 to 1.0)
BOX_THICKNESS = 2               # Thickness of bounding boxes
TEXT_SIZE = 0.6                 # Size of text labels
SHOW_FPS = True                 # Show FPS counter
SHOW_COUNT = True               # Show detection count

# ============================================
# MAIN CODE
# ============================================

def main():
    # Load YOLO model
    print(f"Loading model: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)
    print("Model loaded!")
    
    # Open camera
    print(f"Opening camera: {CAMERA_INDEX}")
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    
    if not cap.isOpened():
        print("ERROR: Cannot open camera!")
        return
    
    print("Camera ready! Press 'q' to quit, 's' to save frame")
    
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break
        
        # Run YOLO detection
        results = model(frame, conf=CONFIDENCE, iou=IOU_THRESHOLD, verbose=False)
        
        # Draw detections
        if results[0].masks is not None:
            masks = results[0].masks.data.cpu().numpy()
            boxes = results[0].boxes.data.cpu().numpy()
            
            # Random colors for each detection
            colors = np.random.randint(0, 255, size=(len(masks), 3), dtype=np.uint8) #Generate random colors for each detected instance. Each color is a 3-element array representing the BGR color values (Blue, Green, Red) used for drawing the masks and bounding boxes on the frame.
            
            for idx, (mask, box) in enumerate(zip(masks, boxes)):
                # Resize mask to frame size
                mask_resized = cv2.resize(mask, (frame.shape[1], frame.shape[0]))
                mask_binary = (mask_resized > 0.5).astype(np.uint8)
                
                # Draw colored mask
                color = colors[idx].tolist()
                colored_mask = np.zeros_like(frame)
                colored_mask[mask_binary == 1] = color
                frame = cv2.addWeighted(frame, 1.0, colored_mask, MASK_ALPHA, 0)
                
                # Draw contours
                contours, _ = cv2.findContours(mask_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(frame, contours, -1, color, BOX_THICKNESS)
                
                # Draw bounding box
                x1, y1, x2, y2, conf, cls = box
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, BOX_THICKNESS)
                
                # Draw label
                class_name = results[0].names[int(cls)]
                label = f"{class_name}: {conf:.2f}"
                (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, TEXT_SIZE, 2)
                cv2.rectangle(frame, (x1, y1 - label_h - 10), (x1 + label_w, y1), color, -1)
                cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, TEXT_SIZE, (255, 255, 255), 2)
        
        # Show FPS
        if SHOW_FPS:
            fps = cap.get(cv2.CAP_PROP_FPS) #get the current frames per second (FPS) of the video capture. This value is used to display the FPS counter on the frame, providing real-time feedback on the performance of the detection process.
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Show detection count
        if SHOW_COUNT:
            num_detections = len(results[0].boxes) if results[0].boxes is not None else 0
            cv2.putText(frame, f"Objects: {num_detections}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Display frame
        cv2.imshow('YOLO Segmentation', frame)
        
        # Handle keyboard input
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            filename = f'capture_{frame_count}.jpg'
            cv2.imwrite(filename, frame)
            print(f"Saved: {filename}")
        
        frame_count += 1
    
    # Cleanup
    cap.release()
    cv2.destroyAllWindows()
    print("Done!")


if __name__ == "__main__":
    main()