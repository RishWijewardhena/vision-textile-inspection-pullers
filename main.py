"""
Main orchestrator - integrates all modules
"""
import os
import sys
import time
import threading
import glob
import cv2
from datetime import datetime
from collections import deque
import random 
import subprocess

# Import all modules
from config import *
from serial_reader import SerialReader
from database import DatabaseHandler
from measurement import StitchMeasurementApp
from file_cleaner import FileCleanerThread
from log_cleaner import clean_old_logs
from mqtt_heartbeat import MqttHeartbeat
from backup_data import BackupDataBuffer
from needle_angle_measure import NeedleAngleWorker
from hardware_utils import find_camera

def tf():
    ''' return the current timestamp in format [HH:MM:SS] '''
    return datetime.now().strftime("[%H:%M:%S]")


def wait_for_camera_nodes(timeout_sec=4.0, poll_interval_sec=0.2):
    """Wait for /dev/video* nodes to appear after driver reload."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        nodes = sorted(glob.glob("/dev/video*"))
        if nodes:
            return True, nodes
        time.sleep(poll_interval_sec)
    return False, sorted(glob.glob("/dev/video*"))


def reload_camera():
    """Reload webcam driver (uvcvideo)."""
    print(tf() + " 🔄 Reloading webcam driver...")
    try:
        subprocess.run(["sudo", "modprobe", "-r", "uvcvideo"], check=True)
        subprocess.run(["sudo", "modprobe", "uvcvideo"], check=True)
        ready, nodes = wait_for_camera_nodes(timeout_sec=4.0, poll_interval_sec=0.2)
        if ready:
            print(tf() + f" ✅ Webcam driver reloaded; camera nodes detected: {nodes}")
        else:
            print(tf() + " ⚠️ Webcam driver reloaded, but no /dev/video* nodes detected yet")
    except subprocess.CalledProcessError as e:
        print(tf() + f" ⚠️ Failed to reload webcam driver: {e}")


def main():
    """Main application loop"""
    print(tf(), "\n" + "="*60)
    print(tf(), "🧵 STITCH MEASUREMENT SYSTEM")
    print(tf(), "="*60)

    # Check calibration files exist
    if not os.path.exists(INTRINSICS_FILE):
        print(tf(), f"❌ Missing calibration file: {INTRINSICS_FILE}")
        sys.exit(1)
    if not os.path.exists(EXTRINSICS_FILE):
        print(tf(), f"❌ Missing extrinsics file: {EXTRINSICS_FILE}")
        sys.exit(1)

    print(tf(), "✅ Calibration files found")
    
    # Step 1: Initialize all components
    print(tf(), "\n📡 Initializing components...")
    
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
        print(tf(), "✅ Measurement app initialized")
        
    except Exception as e:
        print(tf(), f"❌ Failed to initialize measurement app: {e}")
        sys.exit(1)
    
    # Initialize database
    db = DatabaseHandler()
    db_connected = db.connect()
    if not db_connected:
        print(tf(), "⚠️ Database connection failed at startup - will retry on next measurement")
    
    # Note: db object is kept even if connection fails, so reconnection can be attempted during measurement inserts
    
    # Initialize backup data buffer (for failed measurements)
    backup_buffer = BackupDataBuffer()
    
    # reset the total distance in the database to 0 at startup
    if db_connected:
        last_date=db.get_last_record_date()
        today=datetime.now().date()
        
        if last_date is None:
            db.insert_measurement(total_distance=0.0, stitch_length=0.0, seam_allowance=0.0)
            print(tf(), "📊 No previous records - total distance initialized to 0")


        elif last_date!=today:
            db.insert_measurement(
                total_distance=0.0,
                stitch_length=0.0,
                seam_allowance=0.0,
            )
            print(tf(), "🔄 New day detected - total distance reset to 0 in database")
        else:
            print(tf(), f"📊 Total distance continues from last measurement in database: {last_date}")

    
    # Initialize serial reader
    serial_reader = SerialReader()
    if not serial_reader.start_reading():
        print(tf(), "⚠️ Serial connection failed - continuing without serial data")
        serial_reader = None
    
    # Initialize file cleaner
    try:
        file_cleaner = FileCleanerThread()
        file_cleaner.start()
    except Exception as e:
        print(tf(), f"⚠️ File cleaner thread failed to start: {e} (continuing without file cleanup)")
        file_cleaner = None

    # Run one-time log cleanup at startup to free old disk space.
    clean_old_logs()

    # Initialize MQTT heartbeat
    heartbeat = None
    reset_requested = threading.Event()

    def queue_reset_request():
        reset_requested.set()

    try:
        heartbeat = MqttHeartbeat(
            broker=MQTT_SERVER,
            port=MQTT_PORT,
            username=MQTT_USERNAME,
            password=MQTT_PASSWORD,
            topic=MQTT_HEARTBEAT_TOPIC,
            interval_sec=MQTT_HEARTBEAT_INTERVAL,
            tls_insecure=MQTT_TLS_INSECURE,
            reset_topic=MQTT_RESET_TOPIC,
            on_reset=queue_reset_request,
            camera_issue_topic=MQTT_CAMERA_ISSUE_TOPIC,
            esp32_issue_topic=MQTT_ESP32_ISSUE_TOPIC,
            marker_issue_topic=MQTT_MARKER_ISSUE_TOPIC
        )
        heartbeat.start()
        print(tf(), f"✅ MQTT heartbeat started: {MQTT_HEARTBEAT_TOPIC} (every {MQTT_HEARTBEAT_INTERVAL}s)")
    except Exception as e:
        print(tf(), f"⚠️ MQTT heartbeat not started: {e} (continuing without heartbeat)")

    angle_worker = None
    try:
        angle_worker = NeedleAngleWorker(
            model_path=NEEDLE_ANGLE_MODEL_PATH,
            interval_sec=NEEDLE_ANGLE_CHECK_INTERVAL,
            not_rotated_angle_min=NEEDLE_NOT_ROTATED_ANGLE_MIN,
            not_rotated_angle_max=NEEDLE_NOT_ROTATED_ANGLE_MAX,
        )
        angle_worker.start()
        print(
            tf()
            + f" ✅ Needle angle worker started: {NEEDLE_ANGLE_MODEL_PATH} "
            + f"(every {NEEDLE_ANGLE_CHECK_INTERVAL}s, normal range "
            + f"{NEEDLE_NOT_ROTATED_ANGLE_MIN}-{NEEDLE_NOT_ROTATED_ANGLE_MAX}°)"
        )
    except Exception as e:
        print(tf() + f" ⚠️ Needle angle worker not started: {e}")

    print(tf(), "\n" + "="*60)
    print(tf(), "🎯 SYSTEM READY - Starting measurements")
    print(tf(), "="*60)
    print(tf(), "Press 'q' to quit")
    print(tf(), "="*60 + "\n")
    
    # Step 2: Main measurement loop
    last_inference_time = 0
    frame_count = 0

    stitch_delta = 0
    total_distance_mm = float(db.get_last_record_total_distance() if db else 0.0)  # Start from last recorded total distance if DB is available, else 0.0
    if LOG_DEBUG:
        print(tf(), f"📊 Starting total distance: {total_distance_mm:.2f}mm")

    # Create session-specific folder for this run
    session_start = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = os.path.join(SAVE_DIR, session_start)
    os.makedirs(session_dir, exist_ok=True)
    print(tf(), f"📁 Session folder: {os.path.abspath(session_dir)}")
    needle_annotations_dir = os.path.join(session_dir, "needle_angles")
    os.makedirs(needle_annotations_dir, exist_ok=True)
    print(tf() + f" 📁 Needle annotation folder: {os.path.abspath(needle_annotations_dir)}")
    if angle_worker:
        angle_worker.set_annotation_dir(needle_annotations_dir)


    CAMERA_RECONNECT_ATTEMPTS = 0
    MAX_RECONNECT_ATTEMPTS = 10

    # Raw-history buffers (post-offset) used to detect sustained changes
    raw_seam_history = deque(maxlen=10)
    raw_width_history = deque(maxlen=10)

    # Buffer for last 5 valid measurements
        # valid_seam_buffer = deque([6.5] * 5, maxlen=5)
        # valid_width_buffer = deque([3.9] * 5, maxlen=5)
    valid_seam_buffer=deque(maxlen=5)
    valid_width_buffer=deque(maxlen=5)

    # Buffer for marker displacement history (last 20 states)
    marker_displacement_history = deque(maxlen=MARKER_DISPLACEMENT_BUFFER_SIZE)

    RESET_POST_DELAY_SEC = 2.0 

    # reset the ESP32 at startup to ensure it’s in a known state (and to clear any accumulated stitch count)
    if serial_reader:
        serial_success = serial_reader.send_command("R")
        serial_reader.reset_input_buffer()  # Clear any old data after reset command
        time.sleep(10)
        print(tf(), f"\n🔄 Sent initial reset command to ESP32 at startup: {'Success' if serial_success else 'Failed'}")


    # Initialize total distance and stitch count from DB and serial at startup to allow continuity if system restarts
    last_stitch_count = serial_reader.get_stitch_count() if serial_reader else 0
    print(tf(), f"📊 Starting stitch count: {last_stitch_count} (from serial)")

    #retrieve last 5 records from DB to pre-fill smoothing buffers and continue from previous session trends if available
    def initialize_buffers_from_db():
        if db:
            last_records = db.get_last_n_records(5)
            print(tf() + f" 📊 Retrieved last {len(last_records)} records from DB \n {last_records}")
            for record in last_records:
                if record['seam_allowance'] is not None:
                    valid_seam_buffer.append(float(record['seam_allowance']))
                if record['stitch_length'] is not None :
                    valid_width_buffer.append(float(record['stitch_length']))
            print(tf() + f" 📊 Pre-filled smoothing buffers with last {len(valid_seam_buffer)} seam and {len(valid_width_buffer)} width measurements from DB")
        

        print(tf() + f" 📊 Initial valid seam buffer: {list(valid_seam_buffer)}")
        print(tf() + f" 📊 Initial valid width buffer: {list(valid_width_buffer)}")

    #initialize smoothing buffers with recent DB values to allow smoother startup if historical data exists
    initialize_buffers_from_db()

    def perform_reset():
        nonlocal total_distance_mm, last_stitch_count,stitch_delta

        stitch_delta=0
        
        db_success = False
        serial_success = False

        # Attempt DB reset insert (will retry connection if needed)
        db_success = db.insert_measurement(
            total_distance=0.0,
            stitch_length=0.0,
            seam_allowance=0.0,
        )
        if db_success:
            print(tf(), "✅ Reset DB insert succeeded (all zeros)")
            # Try to flush backup buffer after successful reset
            if not backup_buffer.is_empty():
                if backup_buffer.flush_to_db(db):
                    print(tf(), f"✅ Also flushed {len(backup_buffer.get_all())} pending measurements")
        else:
            print(tf(), "⚠️ Reset DB insert failed (will retry on next measurement)")
            # Add reset record to backup if DB fails
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            backup_buffer.add(timestamp, 0.0, 0.0, 0.0)

        if serial_reader:
            serial_success = serial_reader.send_command("R")
            if serial_success:
                print(tf(), "✅ Serial reset command sent: R")
            else:
                print(tf(), "❌ Serial reset command failed: R")
        else:
            print(tf(), "⚠️ Serial reset skipped: serial unavailable")

        time.sleep(RESET_POST_DELAY_SEC)

        total_distance_mm = 0.0
        last_stitch_count = serial_reader.get_stitch_count() if serial_reader else 0
        valid_seam_buffer.clear()
        valid_width_buffer.clear()

        # Re-populate buffers from DB after reset to maintain continuity if data exists
        initialize_buffers_from_db()  
        print(tf(), "🔄 Runtime counters and smoothing buffers reset")

        if db_success and serial_success and heartbeat:
            heartbeat.publish_reset_success()
    
    
    try:
        while True:
            if reset_requested.is_set():
                reset_requested.clear()
                perform_reset()
            
            if not serial_reader or not serial_reader._is_connected():
                time.sleep(1)  # Avoid busy loop if serial reader is unavailable
                if heartbeat:
                    try:
                        heartbeat.publish_esp32_issue()
                    except Exception as e:
                        if LOG_DEBUG:
                            print(tf(), f"❌ Failed to publish ESP32 issue: {e}")

            ret, frame = measurement_app.cap.read()
            if not ret:
                CAMERA_RECONNECT_ATTEMPTS += 1
                print(tf(), f"! No frame from camera (attempt {CAMERA_RECONNECT_ATTEMPTS}/{MAX_RECONNECT_ATTEMPTS})")
                time.sleep(1.5) #short delay before retrying
                
                if heartbeat:
                    try:
                        heartbeat.publish_camera_issue()
                    except Exception as e:
                        if LOG_DEBUG:
                            print(tf(), f"❌ Failed to publish camera issue: {e}")

                if CAMERA_RECONNECT_ATTEMPTS >= MAX_RECONNECT_ATTEMPTS:

                    print(tf(), " Camera disconnected. Attempting to reconnect...")
                    measurement_app.cap.release()
                    time.sleep(1)

                    reload_camera()  # reload the camera for a fresh start
                    time.sleep(0.5)
                    old_camera_index = measurement_app.camera_index
                    detected_camera_index = find_camera()
                    measurement_app.camera_index = detected_camera_index
                    print(
                        tf(),
                        f" 🔎 Camera re-detected before reopen: {old_camera_index} -> {detected_camera_index}",
                    )
                    if measurement_app.reopen_camera(CALIB_W, CALIB_H):
                        print(tf(), "✅ Camera reconnected")
                    else:
                        print(tf(), "❌ Camera reopen failed; will retry")
                    CAMERA_RECONNECT_ATTEMPTS = 0

                time.sleep(0.1)
                continue    

            CAMERA_RECONNECT_ATTEMPTS = 0  # Reset on successful frame
            current_time = time.time()

            if current_time - last_inference_time >= INFERENCE_INTERVAL:
                annotated, measurements = measurement_app.process_frame(frame)

                current_stitch_count = serial_reader.get_stitch_count() if serial_reader else 0

                if angle_worker and angle_worker.maybe_submit(frame, current_time):
                    print(tf() + " 🧭 Needle angle inference queued")
                
                if angle_worker and heartbeat:
                    angle_result = angle_worker.latest_result()
                    if angle_result.get("rotated"):
                        try:
                            heartbeat.client.publish(
                                MQTT_CAMERA_ISSUE_TOPIC,
                                payload="rotated",
                                qos=0,
                                retain=False,
                            )
                            print(tf() + f" MQTT camera issue sent: {MQTT_CAMERA_ISSUE_TOPIC} -> rotated")
                        except Exception as exc:
                            print(tf() + f" ⚠️ MQTT camera rotated publish failed: {exc}")

                # Calculate movement based on stitch count change
                stitch_delta += current_stitch_count - last_stitch_count
                last_stitch_count = current_stitch_count

                # getting the measurements 
                seam_length_mm = measurements.get('edge_distance_mm', None)
                stitch_width_mm = measurements.get('stitch_width_mm', None)

                marker_displaced = measurements.get('marker_displaced', False)
                marker_displacement_history.append(marker_displaced)
                
                # Check if marker displacement threshold is exceeded
                if len(marker_displacement_history) > 0:
                    true_count = sum(marker_displacement_history)
                    displacement_percent = (true_count / len(marker_displacement_history)) * 100
                    
                    if displacement_percent >= MARKER_DISPLACEMENT_THRESHOLD_PERCENT and heartbeat:
                        if LOG_DEBUG:
                            print(tf(), f"!!! Marker displacement detected: {displacement_percent:.1f}% of last {len(marker_displacement_history)} samples")
                        try:
                            heartbeat.publish_marker_issue()
                        except Exception as e:
                            if LOG_DEBUG:
                                print(tf(), f"XX Failed to publish marker issue: {e}")
                    
                #applying the offsets
                if seam_length_mm is not None:
                    seam_length_mm += SEAM_ALLOWANCE_OFFSET_MM 
                    cv2.putText(annotated, f"Adjusted seam: {seam_length_mm:.2f}mm", (20, 90),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                if stitch_width_mm is not None:
                    stitch_width_mm += STITCH_LENGTH_OFFSET_MM
                    cv2.putText(annotated, f"Adjusted width: {stitch_width_mm:.2f}mm", (20, 120),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                if LOG_DEBUG:
                      print(tf(), f" Raw measurements: seam={measurements.get('edge_distance_mm', 'N/A')}mm, "
                          f"width={measurements.get('stitch_width_mm', 'N/A')}mm")
                      print(tf(), f" Adjusted measurements: seam={seam_length_mm if seam_length_mm is not None else 'N/A'}mm, "
                          f"width={stitch_width_mm if stitch_width_mm is not None else 'N/A'}mm")

                # Determine if this is a valid measurement
                valid_seam = (
                    seam_length_mm is not None
                    and Seam_lower_limit < seam_length_mm < Seam_upper_limit
                )

                valid_stitch = (
                    stitch_width_mm is not None
                    and stitch_lower_limit < stitch_width_mm < stitch_upper_limit
                )

                 # store offset-applied raw values for history checks
                if seam_length_mm is not None:
                    raw_seam_history.append(seam_length_mm)
                if stitch_width_mm is not None:
                    raw_width_history.append(stitch_width_mm)

                
                confirmed_override = False

                # If seam is above soft upper limit, check for N consecutive similar samples -> accept
                if not valid_seam and seam_length_mm is not None and seam_length_mm > Seam_upper_limit:
                    recent = [v for v in list(raw_seam_history)[-CONFIRM_CONSECUTIVE:] if v is not None]
                    if len(recent) >= CONFIRM_CONSECUTIVE and all(v > Seam_upper_limit - CONFIRM_TOLERANCE_MM for v in recent):
                        valid_seam = True
                        confirmed_override = True
                        print(tf(), f"!! Confirmed valid seam measurement above upper limit based on recent history: {recent[-CONFIRM_CONSECUTIVE:]}")

                # For small/too-low measurements: ignore (do not confirm below lower bound)
                # If stitch width is above soft upper limit, check similarly
                if not valid_stitch and stitch_width_mm is not None and stitch_width_mm > stitch_upper_limit:
                    recent_w = [v for v in list(raw_width_history)[-CONFIRM_CONSECUTIVE:] if v is not None]
                    if len(recent_w) >= CONFIRM_CONSECUTIVE and all(v > stitch_upper_limit - CONFIRM_TOLERANCE_MM for v in recent_w):
                        valid_stitch = True
                        confirmed_override = True
                        print(tf(), f"!! Confirmed valid stitch measurement above upper limit based on recent history: {recent_w[-CONFIRM_CONSECUTIVE:]}")

                has_valid_measurement = valid_seam and valid_stitch  

                # If valid, save to buffer
                if has_valid_measurement:
                    if confirmed_override:
                        valid_seam_buffer.clear()
                        valid_width_buffer.clear()
                    valid_seam_buffer.append(seam_length_mm)
                    valid_width_buffer.append(stitch_width_mm)
                    if LOG_DEBUG:
                        print(tf(), f"📦 Buffered measurement: seam={seam_length_mm:.2f}mm, width={stitch_width_mm:.2f}mm "
                            f"(buffer size: {len(valid_seam_buffer)}/5)")
                              
                elif len(valid_seam_buffer) > 0 and len(valid_width_buffer) > 0:
                    # No valid measurement — use average of last 5 if available
                    seam_length_mm = sum(valid_seam_buffer) / len(valid_seam_buffer)
                    stitch_width_mm = sum(valid_width_buffer) / len(valid_width_buffer)
                    has_valid_measurement = True
                    if LOG_DEBUG:
                        print(tf(), f" Using buffered average: seam={seam_length_mm:.2f}mm, "
                              f"width={stitch_width_mm:.2f}mm (from {len(valid_seam_buffer)} samples)")
                else:
                    if LOG_DEBUG and stitch_delta > 0:
                        print(tf(), "⚠️ No valid measurement and buffer is empty — skipping DB update")

                if has_valid_measurement and stitch_delta> 0:
                    # Insert to database (only log if there's a new rotation)
                    moved_distance_mm = stitch_delta * stitch_width_mm
                    total_distance_mm += moved_distance_mm

                    # Check if DB reconnected since last failure
                    if not db.connection or not db.connection.is_connected():
                        if db.connect():
                            print(tf(), "🔄 Database reconnected - flushing backup buffer")
                            if not backup_buffer.is_empty():
                                if backup_buffer.flush_to_db(db):
                                    print(tf(), f"✅ Flushed {len(backup_buffer.get_all())} buffered measurements")
                    
                    # Attempt DB insert; will retry connection if needed
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    success = db.insert_measurement(
                        total_distance=round(total_distance_mm, 1),
                        stitch_length=round(stitch_width_mm, 1),
                        seam_allowance=round(seam_length_mm, 1)
                    )
                    
                    if not success:
                        # Add to backup buffer instead of dropping data
                        backup_buffer.add(timestamp, round(total_distance_mm, 1), 
                                        round(stitch_width_mm, 1), round(seam_length_mm, 1))
                        print(tf(), f"⚠️ Database insert failed - backed up to buffer ({backup_buffer.size()}/50)")
                    else:
                        # On successful insert, try to flush any pending backups
                        if not backup_buffer.is_empty():
                            print(tf(), f"📊 DB insert successful. Buffer has {backup_buffer.size()} pending items")

                    info_text = (f"Count: {current_stitch_count} | Count_delta: {stitch_delta} | Moved: {moved_distance_mm:.2f}mm | "
                               f"Total: {total_distance_mm:.2f}mm | Seam: {seam_length_mm:.2f}mm")
                    if stitch_width_mm is not None:
                        info_text += f" | Width: {stitch_width_mm:.2f}mm"

                    cv2.putText(annotated, info_text, (10, annotated.shape[0] - 40),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                    
                    stitch_delta=0 # reset the stich delta
                    print(tf(), f"📏 {info_text}")
          

                else:
                    cv2.putText(annotated, f"Stitch count: {current_stitch_count} (waiting for measurements)",
                              (10, annotated.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join(session_dir, f"frame_{frame_count:05d}_{timestamp}.jpg")
                cv2.imwrite(save_path, annotated)
                
                # Save unannotated frame to Photos subdirectory if enabled
                if SAVE_UNANNOTATED_IMAGE:
                    photos_dir = os.path.join(session_dir, "Photos")
                    os.makedirs(photos_dir, exist_ok=True)
                    raw_save_path = os.path.join(photos_dir, f"original_frame_{frame_count:05d}_{timestamp}.jpg")
                    cv2.imwrite(raw_save_path, frame)

                if SHOW_WINDOWS:
                    cv2.imshow("Stitch Measurement System", annotated)
                last_inference_time = current_time
                frame_count += 1
            else:
                if SHOW_WINDOWS:
                    cv2.imshow("Stitch Measurement System", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print(tf(), "\n🛑 Shutdown requested by user")
                break
    
    except KeyboardInterrupt:
        print(tf(), "\n🛑 Interrupted by user")
    
    finally:
        print(tf(), "\n🧹 Cleaning up...")

        if serial_reader:
            serial_reader.stop()
        if db:
            # Try to flush any remaining backup data before closing
            if not backup_buffer.is_empty():
                print(tf(), f"📊 Attempting to flush {backup_buffer.size()} remaining measurements before shutdown...")
                if backup_buffer.flush_to_db(db):
                    print(tf(), "✅ Successfully flushed remaining measurements")
                else:
                    print(tf(), f"⚠️ {backup_buffer.size()} measurements remain in backup (will flush on restart)")
            db.close()
        if heartbeat:
            heartbeat.stop()
        if file_cleaner:
            file_cleaner.stop()

        measurement_app.cap.release()
        cv2.destroyAllWindows()

        print(tf(), f"\n✅ Total frames processed: {frame_count}")
        print(tf(), f"📁 Images saved to: {os.path.abspath(session_dir)}")
        print(tf(), "\n👋 System shutdown complete")


if __name__ == "__main__":
    main()
