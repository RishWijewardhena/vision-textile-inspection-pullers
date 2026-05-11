# THREAD - Textile Stitch Measurement System

## Project Overview

**THREAD** (Textile Stitch Measurement System) is an automated computer vision-based fabric inspection system designed to measure stitch quality metrics in real-time during textile manufacturing. The system uses deep learning (YOLOv8 segmentation models) combined with camera calibration and serial communication with ESP32 microcontrollers to accurately measure stitch length and seam allowance.

### Key Features

- **Real-time Stitch Detection**: YOLOv8 segmentation model detects and measures individual stitches
- **Calibrated Measurements**: Uses camera intrinsics/extrinsics and ChArUco board calibration for pixel-to-world-space conversion
- **Serial Integration**: Communicates with ESP32 via serial to get stitch count feedback
- **Database Logging**: Stores measurements in MySQL for historical tracking and analysis
- **MQTT Monitoring**: Publishes heartbeats and status updates to MQTT broker
- **Smart Reset**: Remote reset capability via MQTT topic to reset counters and databases
- **Automated Cleanup**: Background thread cleans up old annotation images based on retention policy

---

## Project Structure

```
THREAD/
├── main.py                          # Main application orchestrator
├── config.py                        # Central configuration file
├── requirements.txt                 # Python dependencies
├── camera_calibration.json          # Camera intrinsic parameters
├── camera_extrinsics.json           # Camera extrinsic parameters (pose)
├── auto_run.sh                      # Auto-start script
├── auto_runner.sh                   # Alternative auto-start script
│
├── Core Modules/
│   ├── measurement.py               # YOLO inference & stitch detection
│   ├── serial_reader.py             # ESP32 serial communication
│   ├── database.py                  # MySQL database operations
│   ├── mqtt_heartbeat.py            # MQTT client & messaging
│   ├── file_cleaner.py              # Background file cleanup thread
│   ├── hardware_utils.py            # Hardware detection utilities
│
├── Utils/                           # Model files & utility scripts
│   ├── best_puller_model.pt         # YOLOv8 stitch detection model
│   ├── testing_model.py             # Model testing utilities
│   ├── usb_camera.py                # USB camera utilities
│   ├── capture_camera.py            # Camera capture utilities
│   └── ...                          # Other model variants
│
├── Other models/                    # Alternative model files
│   ├── best_contrast.pt
│   └── yolov8n_seg_200.pt
│
├── logs/                            # System logs directory
├── saved_annotations/               # Captured frames & measurements
│   └── YYYY-MM-DD_HH-MM-SS/        # Session-specific folders
│
├── scripts/                         # Helper scripts
│   └── grating_passwordless_sudo.sh # Sudo configuration
│
└── docs/                            # Documentation (this folder)
    └── overview.md                  # This file
```

---

## Module Descriptions

### 1. **main.py** - Main Orchestrator
**Purpose**: Central coordinator that manages all components and implements the main measurement loop

**Key Responsibilities**:
- Initialize all modules (measurement app, database, serial reader, MQTT, file cleaner)
- Implement main frame processing loop
- Handle stitch detection, measurement buffering, and smoothing
- Manage database inserts with valid measurements
- Handle reset requests from MQTT
- Graceful shutdown and cleanup

**Key Functions**:
- `main()`: Main application loop
- `perform_reset()`: Reset counters and database on MQTT command
- `reload_camera()`: Reload webcam driver when connection issues occur
- `queue_reset_request()`: MQTT callback to trigger reset

---

### 2. **config.py** - Configuration Management
**Purpose**: Centralized configuration for the entire system

**Configuration Categories**:

#### Camera Calibration
- ChArUco board parameters (marker size, grid dimensions)
- Calibration file paths

#### Camera Settings
- Camera index detection
- Resolution (1280×960)
- Auto-exposure mode

#### YOLO Model
- Model path selection
- Confidence and IOU thresholds
- Class IDs for stitch and marker detection

#### Measurement Thresholds
- Valid measurement ranges (seam: 3.5-7.5mm, stitch: 2.5-4.5mm)
- Outlier filtering parameters
- Measurement offsets for calibration correction

#### Serial Communication
- Port auto-detection (ESP32)
- Baud rate (115200)
- Timeout settings

#### Database
- MySQL connection parameters
- Table configuration

#### MQTT
- Broker connection details
- Heartbeat interval and topics
- Reset topic configuration

---

### 3. **measurement.py** - Computer Vision Processing
**Purpose**: YOLO inference and stitch measurement calculations

**Key Components**:
- **YOLO Model Loader**: Loads pre-trained segmentation model
- **Camera Calibration**: Loads intrinsic/extrinsic matrices
- **Pixel-to-World Conversion**: Converts pixel coordinates to millimeters using camera parameters
- **Stitch Detection**: Identifies stitch and fabric edge markers
- **Measurement Calculation**: Computes stitch width and seam allowance

**Key Methods**:
- `StitchMeasurementApp.process_frame()`: Main inference pipeline
- `pixel_to_world()`: Ray-plane intersection for 3D coordinate conversion
- `marker_far_edge_envelope()`: Identifies fabric edge reference line
- `filtered_mean()`: Robust mean calculation with outlier removal
- `kmeans_1d_two_clusters()`: Clusters stitches into two rows if present

---

### 4. **serial_reader.py** - ESP32 Communication
**Purpose**: Thread-safe serial communication with ESP32 microcontroller

**Key Features**:
- **Background Thread**: Reads stitch count continuously in separate thread
- **Thread Safety**: Uses locks to prevent race conditions
- **Auto-Reconnection**: Attempts to reconnect if connection drops
- **Buffer Management**: Parses serial messages and maintains stitch count

**Key Methods**:
- `start_reading()`: Start background thread
- `get_stitch_count()`: Thread-safe stitch count retrieval
- `send_command()`: Send commands to ESP32 (e.g., "R" for reset)
- `stop()`: Gracefully stop thread

---

### 5. **database.py** - MySQL Storage
**Purpose**: Persistent storage of measurements

**Key Operations**:
- Store measurements: stitch length, seam allowance, total distance
- Query last record date for daily reset detection
- Retrieve last N records for buffer initialization
- Get total distance for continuity after restart

**Key Methods**:
- `insert_measurement()`: Log a new measurement
- `get_last_record_date()`: Check if new day detected
- `get_last_record_total_distance()`: Get running total
- `get_last_n_records()`: Retrieve historical data

---

### 6. **mqtt_heartbeat.py** - Remote Monitoring & Control
**Purpose**: MQTT client for heartbeat publishing and remote control

**Key Features**:
- **Periodic Heartbeat**: Publishes alive status at regular intervals
- **Reset Topic**: Listens for reset commands from broker
- **Status Topics**: Publishes camera/ESP32 issue status
- **TLS Support**: Secure connection to MQTT broker

**Key Methods**:
- `on_message()`: Handle incoming MQTT messages
- `_on_connect()`: Subscribe to control topics
- `publish_reset_success()`: Confirm reset completion

---

### 7. **file_cleaner.py** - Automated Cleanup
**Purpose**: Background maintenance to manage disk space

**Key Features**:
- **Periodic Cleanup**: Runs at configured intervals (every hour)
- **Retention Policy**: Deletes files older than 96 hours (4 days)
- **Recursive Deletion**: Cleans annotation images from session folders
- **Empty Directory Removal**: Removes empty session folders

---

### 8. **hardware_utils.py** - Hardware Detection
**Purpose**: Auto-detect and configure hardware components

**Key Functions**:
- `find_esp32()`: Detect ESP32 via USB VID/PID
- `find_camera()`: Detect available webcam from known device paths

---

## Main Workflow Flowchart

```
┌─────────────────────────────────────────────────────────────────┐
│                    SYSTEM STARTUP                               │
├─────────────────────────────────────────────────────────────────┤
│  1. Load configuration from config.py                           │
│  2. Check calibration files exist                               │
│  3. Initialize StitchMeasurementApp (YOLO + Camera)             │
│  4. Initialize DatabaseHandler                                  │
│  5. Check for new day & reset DB if needed                      │
│  6. Initialize SerialReader (ESP32)                             │
│  7. Initialize FileCleanerThread                                │
│  8. Initialize MqttHeartbeat                                    │
│  9. Pre-populate smoothing buffers from DB                      │
│ 10. Send initial reset to ESP32                                 │
└──────────┬──────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MAIN MEASUREMENT LOOP                         │
├─────────────────────────────────────────────────────────────────┤
│  while True:                                                    │
│    Check for MQTT reset request                                 │
│        └─→ If set: perform_reset() [see reset workflow]         │
│    Capture frame from camera                                    │
│        └─→ If failed: attempt reconnection                      │
│    If inference interval elapsed:                               │
│        └─→ Run frame processing [see frame processing workflow] │
│    Display/save annotated frame                                 │
│    Check for 'q' key to quit                                    │
└──────────┬──────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   GRACEFUL SHUTDOWN                             │
├─────────────────────────────────────────────────────────────────┤
│  1. Stop SerialReader thread                                    │
│  2. Close database connection                                   │
│  3. Stop MQTT client                                            │
│  4. Stop FileCleanerThread                                      │
│  5. Release camera                                              │
│  6. Close all windows                                           │
│  7. Print final stats and session folder path                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Frame Processing Workflow Flowchart

```mermaid
flowchart TD
    A["Capture Frame from Camera"] --> B["Run YOLO Inference"]
    B --> C["Extract Stitch & Marker Masks"]
    C --> D["Get Current Stitch Count from ESP32"]
    D --> E["Calculate stitch_delta = current_count - last_count"]
    
    E --> F["For Each Detected Stitch:"]
    F --> G["Find Closest Fabric Edge<br/>Calculate Pixel Distance<br/>Convert to Millimeters"]
    G --> H["Apply Seam Allowance Offset<br/>Apply Stitch Length Offset"]
    H --> I["Obtain: seam_length_mm,<br/>stitch_width_mm"]
    
    I --> J{"Both measurements<br/>in valid range?"}
    
    J -->|Yes| K["Buffer Valid"]
    J -->|No| L{"Exceeds upper limit<br/>AND confirmed by<br/>N consecutive samples?"}
    L -->|Yes| M["Confirmed Override<br/>Mark as Valid"]
    L -->|No| N["Mark as Invalid"]
    
    K --> O["Append to<br/>valid_seam_buffer<br/>valid_width_buffer"]
    M --> O
    N --> P{"Buffers have<br/>data?"}
    
    P -->|Yes| Q["Use Average of Last 5<br/>Add Random Noise"]
    P -->|No| R["Skip Database Update"]
    
    O --> S{"has_valid_measurement<br/>AND stitch_delta > 0?"}
    Q --> S
    
    S -->|Yes| T["Calculate moved_distance<br/>=stitch_delta × stitch_width"]
    T --> U["Accumulate total_distance"]
    U --> V["Insert to Database:<br/>total_distance, stitch_length,<br/>seam_allowance"]
    V --> W["Reset stitch_delta = 0<br/>Save Annotated Frame"]
    W --> X["Print Measurement Info"]
    
    S -->|No| Y["Display 'Waiting for<br/>Measurements'"]
    R --> Y
    
    X --> Z["End Frame Processing"]
    Y --> Z
```

---

## Reset Workflow Flowchart

```mermaid
flowchart TD
    A["Reset Request Detected<br/>from MQTT"] --> B["Reset stitch_delta = 0"]
    
    B --> C["Database Reset:<br/>Insert row with all zeros"]
    C --> D{"DB Insert<br/>Successful?"}
    D -->|Yes| E["✓ DB Reset Success"]
    D -->|No| F["✗ DB Reset Failed"]
    
    E --> G["Serial Reset:<br/>Send R Command to ESP32"]
    F --> G
    
    G --> H{"Serial Command<br/>Successful?"}
    H -->|Yes| I["✓ Serial Reset Success"]
    H -->|No| J["✗ Serial Reset Failed"]
    
    I --> K["Wait RESET_POST_DELAY_SEC<br/>2 seconds"]
    J --> K
    
    K --> L["Update Runtime State:<br/>total_distance_mm = 0.0"]
    L --> M["Get latest stitch_count<br/>from ESP32"]
    M --> N["Clear valid_seam_buffer"]
    N --> O["Clear valid_width_buffer"]
    
    O --> P["Re-initialize Buffers:<br/>Pull last 5 records from DB"]
    P --> Q["Populate buffers with<br/>historical trends"]
    
    Q --> R{"Both DB and Serial<br/>Succeeded?"}
    R -->|Yes| S["MQTT Publish:<br/>reset_success"]
    R -->|No| T["Log Reset Issues"]
    
    S --> U["Return to Main Loop"]
    T --> U
```

---

## Serial Communication Workflow Flowchart

```mermaid
flowchart TD
    A["Serial Reader Initialization"] --> B["Auto-detect ESP32<br/>VID:PID 0x303A:0x1001"]
    B --> C{"ESP32 Found?"}
    C -->|Yes| D["Establish Serial Connection<br/>115200 baud"]
    C -->|No| E["Fallback to ENV SERIAL_PORT"]
    
    D --> F["Create Background Thread"]
    E --> F
    F --> G["Start Reading Thread"]
    
    G --> H["Background Serial<br/>Reading Thread"]
    
    H --> I["while running:"]
    I --> J["Read Data from Serial Port"]
    J --> K["Parse Message<br/>Expected: integer stitch count"]
    K --> L["Acquire Thread Lock"]
    L --> M["Update latest_stitch_count"]
    M --> N["Release Thread Lock"]
    
    N --> O{"Connection<br/>Lost?"}
    O -->|Yes| P["Attempt Auto-Reconnect"]
    O -->|No| Q["Sleep briefly"]
    P --> J
    Q --> J
    
    H --> R["Main Thread Query"]
    R --> S["get_stitch_count() called"]
    S --> T["Acquire Thread Lock"]
    T --> U["Return latest_stitch_count<br/>Thread-safe"]
    U --> V["Release Thread Lock"]
    
    H --> W["Send Command to ESP32"]
    W --> X["send_command: R"]
    X --> Y{"Connection<br/>Open?"}
    Y -->|Yes| Z["Encode Command UTF-8"]
    Y -->|No| AA["Attempt Reconnect"]
    Z --> AB["Write to Serial Port"]
    AB --> AC["Flush Buffer"]
    AC --> AD["Return Success"]
    AA --> AE["Return Failure"]
```

---

## Database Workflow Flowchart

```mermaid
flowchart TD
    A["Database Initialization"] --> B["Read Config from config.py"]
    B --> C["Attempt MySQL Connection"]
    C --> D{"Connection<br/>Successful?"}
    D -->|Yes| E["✓ DB Connected"]
    D -->|No| F["✗ Log Warning<br/>Continue without DB"]
    
    E --> G["Query Last Record Date"]
    G --> H{"Last Record<br/>Date exists?"}
    H -->|No| I["Insert Row of Zeros<br/>Initialize total_distance"]
    H -->|Yes| J{"Last Record Date<br/>== Today?"}
    J -->|No| K["New Day Detected<br/>Insert Row of Zeros"]
    J -->|Yes| L["Same Day<br/>Continue with existing data"]
    
    I --> M["Retrieve Last N Records<br/>for Buffer Initialization"]
    K --> M
    L --> M
    
    F --> N["Operation Mode:<br/>Without Database"]
    
    M --> O["Periodic Measurement Insert"]
    N --> O
    
    O --> P{"Frame has valid<br/>measurement?"}
    P -->|Yes| Q["Calculate total_distance<br/>accumulated"]
    P -->|No| R["Skip Insert"]
    
    Q --> S["Prepare Record:<br/>- timestamp<br/>- stitch_length<br/>- seam_allowance<br/>- total_distance"]
    S --> T["Execute INSERT Query"]
    T --> U["Commit Transaction"]
    U --> V{"Insert<br/>Successful?"}
    V -->|Yes| W["✓ Record Stored"]
    V -->|No| X["✗ Log Failure<br/>Retry on next measurement"]
    
    W --> Y["Restart Continuity"]
    X --> Y
    R --> Y
    
    Y --> Z["System Startup:"]
    Z --> AA["get_last_record_date()"]
    AA --> AB["Check if new day"]
    AB --> AC["get_last_record_total_distance()"]
    AC --> AD["Resume from last total"]
    AD --> AE["get_last_n_records 5"]
    AE --> AF["Populate smoothing buffers"]
    AF --> AG["✓ Seamless Resume"]
```

---

## MQTT Control Workflow Flowchart

```mermaid
flowchart TD
    A["MQTT Heartbeat Initialization"] --> B["Create MQTT Client<br/>with TLS Support"]
    B --> C["Set Username/Password<br/>Credentials"]
    C --> D["Subscribe to:<br/>- Reset Topic<br/>- Control Topics"]
    D --> E["Connect to Broker"]
    E --> F["Start Background Thread"]
    
    F --> G["Periodic Heartbeat<br/>Publishing"]
    G --> H["Every MQTT_HEARTBEAT_INTERVAL<br/>seconds:"]
    H --> I{"Still Connected<br/>to Broker?"}
    I -->|Yes| J["Publish Alive Status<br/>on Heartbeat Topic"]
    I -->|No| K["Attempt Reconnect<br/>Exponential Backoff"]
    J --> L["Sleep until Next Interval"]
    K --> L
    
    F --> M["Incoming Message Handler<br/>on_message Callback"]
    M --> N{"Check Message<br/>Topic"}
    
    N -->|Reset Topic| O["Call on_reset Callback"]
    O --> P["queue_reset_request"]
    P --> Q["Set reset_requested.Event"]
    Q --> R["Main Thread Detects Reset"]
    R --> S["perform_reset Executed"]
    
    N -->|Camera Issue Topic| T["Publish Camera Problem<br/>Status"]
    
    N -->|ESP32 Issue Topic| U["Publish ESP32 Problem<br/>Status"]
    
    N -->|Other Topic| V["Handle/Ignore"]
    
    S --> W["Reset Sequence<br/>Completes"]
    T --> X["Monitor Updated"]
    U --> X
    V --> Y["Wait for Next Message"]
    W --> Y
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                  HARDWARE LAYER                                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  USB Camera  │    │   ESP32      │    │ MQTT Broker  │       │
│  │ (1280x960)   │    │ (Stitch Cnt) │    │ (Remote Ctrl)│       │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘       │
└─────────┼────────────────────┼─────────────────┼────────────────┘
          │                    │                 │
          ▼                    ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                 SOFTWARE LAYER                                   │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │ measurement.py   │  │ serial_reader.py │  │ mqtt_hb.py   │   │
│  │ (YOLO + calib)   │  │ (Thread-safe)    │  │ (Listener)   │   │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘   │
│           │                     │                  │             │
│           └─────────────────────┼──────────────────┘             │
│                                 ▼                                │
│                        ┌──────────────────────┐                  │
│                        │     main.py          │                  │
│                        │  (Orchestrator)      │                  │
│                        └─────────┬────────────┘                  │
│                                  ▼                               │
│                        ┌──────────────────────┐                  │
│                        │   database.py        │                  │
│                        │  (MySQL Storage)     │                  │
│                        └──────────────────────┘                  │
│                                                                  │
│                        ┌──────────────────────┐                  │
│                        │  file_cleaner.py     │                  │
│                        │  (Background Cleanup)│                  │
│                        └──────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                  STORAGE LAYER                                   │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐    ┌──────────────────────────────────┐   │
│  │ MySQL Database   │    │ Filesystem (Annotations)         │   │
│  │ - Measurements   │    │ - saved_annotations/             │   │
│  │ - Running totals │    │   └─ SESSION_ID/                 │   │
│  │ - History        │    │      └─ frame_XXXXX.jpg          │   │
│  └──────────────────┘    └──────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Configuration Parameters Summary

### Key Measurement Limits
| Parameter | Value | Purpose |
|-----------|-------|---------|
| `Seam_upper_limit` | 7.5 mm | Max acceptable seam allowance |
| `Seam_lower_limit` | 3.5 mm | Min acceptable seam allowance |
| `stitch_upper_limit` | 4.5 mm | Max acceptable stitch width |
| `stitch_lower_limit` | 2.5 mm | Min acceptable stitch width |

### Key Offsets
| Parameter | Default | Purpose |
|-----------|---------|---------|
| `STITCH_LENGTH_OFFSET_MM` | -0.3 | Calibration correction for stitch width |
| `SEAM_ALLOWANCE_OFFSET_MM` | 3.5 | Calibration correction for seam |

### Performance Settings
| Parameter | Value | Purpose |
|-----------|-------|---------|
| `INFERENCE_INTERVAL` | 2 seconds | Gap between YOLO inferences |
| `FRAME_BUFFER` | 4 frames | Median filter window |
| `CONFIRM_CONSECUTIVE` | 4 | Consecutive samples to confirm outlier |
| `FILE_RETENTION_HOURS` | 96 hours | Keep files for 4 days |
| `FILE_CLEANUP_INTERVAL_SECONDS` | 3600 | Check cleanup every hour |

---

## Error Handling & Resilience

### Camera Disconnection
- Monitors for failed frame captures
- Retries up to 10 times with 100ms delay
- Reloads webcam driver (`uvcvideo`) on prolonged failure
- Publishes camera issue to MQTT

### Serial Communication
- Automatic port detection via VID/PID
- Connection loss detection and auto-reconnect
- Thread-safe data access with locking
- Graceful fallback if ESP32 unavailable

### Database Failures
- Continues operation without DB if connection fails
- Retries insert on next valid measurement
- Publishes status to MQTT for monitoring

### MQTT Connection Issues
- Auto-reconnect with exponential backoff
- Gracefully continues if broker unavailable
- Reset requests queued and processed on reconnection

---

## Performance Characteristics

- **Frame Processing**: ~2 second interval between inferences
- **Measurement Buffering**: Last 5 valid measurements smoothed
- **Thread Safety**: Locks on serial communication and shared counters
- **Memory**: Circular buffers limited to 5-10 samples each
- **Disk Usage**: ~96 hour retention policy with automatic cleanup

---

## Dependencies

```
numpy               - Numerical computing
opencv-contrib-python - Computer vision & UI
pillow              - Image processing
scipy               - Scientific computing (filtering)
matplotlib          - Visualization (optional)
paho-mqtt           - MQTT client
pyserial            - Serial communication
mysql-connector-python - MySQL access
python-dotenv       - Environment variable management
ultralytics         - YOLOv8 framework
requests            - HTTP library
PyYAML              - YAML parsing
```

---

## Getting Started

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment** (`.env` file):
   ```
   DB_HOST=localhost
   DB_USER=textile_user
   DB_PASSWORD=secure_password
   DB_DATABASE=stitch_measurements
   DB_TABLE=measurements
   
   MQTT_SERVER=mqtt.example.com
   MQTT_PORT=8883
   MQTT_USERNAME=system_user
   MQTT_PASSWORD=mqtt_password
   
   STITCH_LENGTH_OFFSET_MM=-0.3
   SEAM_ALLOWANCE_OFFSET_MM=3.5
   ```

3. **Calibrate Camera** (if needed):
   - Use ChArUco board calibration app
   - Update `camera_calibration.json` and `camera_extrinsics.json`

4. **Run System**:
   ```bash
   python main.py
   ```

5. **Monitor** via MQTT:
   - Subscribe to heartbeat topic for alive status
   - Send reset command to reset topic
   - Check camera/ESP32 issue topics

---

## Future Enhancements

- [ ] Web dashboard for live monitoring
- [ ] Statistical analysis and trend reporting
- [ ] Multiple camera support
- [ ] Advanced defect classification
- [ ] Machine learning-based threshold optimization
- [ ] Integration with factory MES systems
- [ ] Real-time alerting on quality issues

---

**Last Updated**: May 11, 2026  
**Version**: 1.0
