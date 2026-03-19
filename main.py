"""
Main orchestrator - integrates all modules
"""
import os
import sys
import time
import cv2
from datetime import datetime
from collections import deque

# Import all modules
from config import *
from serial_reader import SerialReader
from database import DatabaseHandler
from measurement import StitchMeasurementApp, force_camera_resolution
from file_cleaner import FileCleanerThread
from mqtt_heartbeat import MqttHeartbeat


def main():
    """Main application loop"""
    print("\n" + "="*60)
    print("🧵 STITCH MEASUREMENT SYSTEM")
    print("="*60)

    # Check calibration files exist
    if not os.path.exists(INTRINSICS_FILE):
        print(f"❌ Missing calibration file: {INTRINSICS_FILE}")
        sys.exit(1)
    if not os.path.exists(EXTRINSICS_FILE):
        print(f"❌ Missing extrinsics file: {EXTRINSICS_FILE}")
        sys.exit(1)

    print("✅ Calibration files found")
    
    # Step 1: Initialize all components
    print("\n📡 Initializing components...")
    
    try:
        measurement_app = StitchMeasurementApp(
            calib_path=INTRINSICS_FILE,
            extr_path=EXTRINSICS_FILE,
            model_path=MODEL_PATH,
            camera_index=CAMERA_INDEX,
            calib_w=CALIB_W,
            calib_h=CALIB_H,
            frame_buffer=FRAME_BUFFER,
            min_stitches=MIN_STITCHES,
            stitch_id=STITCH_CLASS_ID,
            marker_id=MARKER_CLASS_ID
        )
        print("✅ Measurement app initialized")
        
    except Exception as e:
        print(f"❌ Failed to initialize measurement app: {e}")
        sys.exit(1)
    
    # Initialize database
    db = DatabaseHandler()
    if not db.connect():
        print("❌ Database connection failed - continuing without DB")
        db = None

    # reset the total distance in the database to 0 at startup
    if db:
        last_date=db.get_last_record_date()
        today=datetime.now().date()
        if last_date!=today:
            db.insert_measurement(
                total_distance=0.0,
                stitch_length=0.0,
                seam_allowance=0.0,
            )
            print("🔄 New day detected - total distance reset to 0 in database")
        else:
            print(f"📊 Total distance continues from last measurement in database: {last_date}")

    
    # Initialize serial reader
    serial_reader = SerialReader()
    if not serial_reader.start_reading():
        print("⚠️ Serial connection failed - continuing without serial data")
        serial_reader = None
    
    # Initialize file cleaner
    try:
        file_cleaner = FileCleanerThread()
        file_cleaner.start()
    except Exception as e:
        print(f"⚠️ File cleaner thread failed to start: {e} (continuing without file cleanup)")
        file_cleaner = None

    # Initialize MQTT heartbeat
    heartbeat = None
    try:
        heartbeat = MqttHeartbeat(
            broker=MQTT_SERVER,
            port=MQTT_PORT,
            username=MQTT_USERNAME,
            password=MQTT_PASSWORD,
            topic=MQTT_HEARTBEAT_TOPIC,
            interval_sec=MQTT_HEARTBEAT_INTERVAL,
            tls_insecure=MQTT_TLS_INSECURE,
        )
        heartbeat.start()
        print(f"✅ MQTT heartbeat started: {MQTT_HEARTBEAT_TOPIC} (every {MQTT_HEARTBEAT_INTERVAL}s)")
    except Exception as e:
        print(f"⚠️ MQTT heartbeat not started: {e} (continuing without heartbeat)")

    print("\n" + "="*60)
    print("🎯 SYSTEM READY - Starting measurements")
    print("="*60)
    print("Press 'q' to quit")
    print("="*60 + "\n")
    
    # Step 2: Main measurement loop
    last_inference_time = 0
    frame_count = 0
    last_stitch_count = 0
    total_distance_mm = 0.0

    # Create session-specific folder for this run
    session_start = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = os.path.join(SAVE_DIR, session_start)
    os.makedirs(session_dir, exist_ok=True)
    print(f"📁 Session folder: {os.path.abspath(session_dir)}")

    CAMERA_RECONNECT_ATTEMPTS = 0
    MAX_RECONNECT_ATTEMPTS = 10

    # Buffer for last 5 valid measurements
    valid_seam_buffer = deque(maxlen=5)
    valid_width_buffer = deque(maxlen=5)

    try:
        while True:
            ret, frame = measurement_app.cap.read()
            if not ret:
                CAMERA_RECONNECT_ATTEMPTS += 1
                print(f"⚠️ No frame from camera (attempt {CAMERA_RECONNECT_ATTEMPTS}/{MAX_RECONNECT_ATTEMPTS})")

                if CAMERA_RECONNECT_ATTEMPTS >= MAX_RECONNECT_ATTEMPTS:
                    print("❌ Camera disconnected. Attempting to reconnect...")
                    measurement_app.cap.release()
                    time.sleep(1)
                    measurement_app.cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)
                    force_camera_resolution(measurement_app.cap, CALIB_W, CALIB_H)
                    CAMERA_RECONNECT_ATTEMPTS = 0

                time.sleep(0.1)
                continue

            CAMERA_RECONNECT_ATTEMPTS = 0  # Reset on successful frame
            current_time = time.time()

            if current_time - last_inference_time >= INFERENCE_INTERVAL:
                annotated, measurements = measurement_app.process_frame(frame)

                current_stitch_count = serial_reader.get_stitch_count() if serial_reader else 0

                # Initialize variables to prevent UnboundLocalError
                stitch_delta = 0
                moved_distance_mm = 0.0

                seam_length_mm = measurements.get('edge_distance_mm', None)
                stitch_width_mm = measurements.get('stitch_width_mm', None)

                # Determine if this is a valid measurement
                has_valid_measurement = (seam_length_mm is not None and stitch_width_mm is not None)

                if has_valid_measurement:
                    # Apply offsets from config
                    seam_length_mm += SEAM_ALLOWANCE_MM
                    stitch_width_mm += STITCH_LENGTH_OFFSET_MM

                    if LOG_DEBUG:
                        print(f"✅ Valid measurement: seam={seam_length_mm:.2f}mm, width={stitch_width_mm:.2f}mm")

                # If valid, save to buffer
                if has_valid_measurement:
                    valid_seam_buffer.append(seam_length_mm)
                    valid_width_buffer.append(stitch_width_mm)
                    if LOG_DEBUG:
                        print(f"📦 Buffered measurement: seam={seam_length_mm:.2f}mm, width={stitch_width_mm:.2f}mm "
                              f"(buffer size: {len(valid_seam_buffer)}/5)")
                elif len(valid_seam_buffer) > 0 and len(valid_width_buffer) > 0:
                    # No valid measurement — use average of last 5 if available
                    seam_length_mm = sum(valid_seam_buffer) / len(valid_seam_buffer)
                    stitch_width_mm = sum(valid_width_buffer) / len(valid_width_buffer)
                    has_valid_measurement = True
                    if LOG_DEBUG:
                        print(f"📊 Using buffered average: seam={seam_length_mm:.2f}mm, "
                              f"width={stitch_width_mm:.2f}mm (from {len(valid_seam_buffer)} samples)")
                else:
                    if LOG_DEBUG:
                        print("⚠️ No valid measurement and buffer is empty — skipping DB update")

                # Single movement calculation (removed duplicate block)
                if has_valid_measurement and stitch_width_mm is not None:
                    stitch_delta = current_stitch_count - last_stitch_count
                    moved_distance_mm = stitch_delta * stitch_width_mm
                    total_distance_mm += moved_distance_mm
                    last_stitch_count = current_stitch_count

                if has_valid_measurement and current_stitch_count > 0:
                    # Insert to database (only log if there's a new rotation)
                    if db and stitch_delta > 0:
                        success = db.insert_measurement(
                            total_distance=total_distance_mm,
                            stitch_length=stitch_width_mm,
                            seam_allowance=seam_length_mm,
                        )
                        if not success:
                            print("⚠️ Database insert failed - will retry on next valid measurement")

                    info_text = (f"Count: {current_stitch_count} | Count_delta: {stitch_delta} | Moved: {moved_distance_mm:.2f}mm | "
                               f"Total: {total_distance_mm:.2f}mm | Seam: {seam_length_mm:.2f}mm")
                    if stitch_width_mm:
                        info_text += f" | Width: {stitch_width_mm:.2f}mm"

                    cv2.putText(annotated, info_text, (10, annotated.shape[0] - 40),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                    print(f"📏 {info_text}")
                else:
                    cv2.putText(annotated, f"Stitch count: {current_stitch_count} (waiting for measurements)",
                              (10, annotated.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join(session_dir, f"frame_{frame_count:05d}_{timestamp}.jpg")
                cv2.imwrite(save_path, annotated)

                if SHOW_WINDOWS:
                    cv2.imshow("Stitch Measurement System", annotated)
                last_inference_time = current_time
                frame_count += 1
            else:
                if SHOW_WINDOWS:
                    cv2.imshow("Stitch Measurement System", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("\n🛑 Shutdown requested by user")
                break
    
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    
    finally:
        print("\n🧹 Cleaning up...")

        if serial_reader:
            serial_reader.stop()
        if db:
            db.close()
        if heartbeat:
            heartbeat.stop()
        if file_cleaner:
            file_cleaner.stop()

        measurement_app.cap.release()
        cv2.destroyAllWindows()

        print(f"\n✅ Total frames processed: {frame_count}")
        print(f"📁 Images saved to: {os.path.abspath(session_dir)}")
        print("\n👋 System shutdown complete")


if __name__ == "__main__":
    main()