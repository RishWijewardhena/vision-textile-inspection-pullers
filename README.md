# Vision Textile Inspection pullers

A computer vision-based fabric inspection system using deep learning for inspect the qualities in textiles like stitch length and the seam allowance.

![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Overview

This project implements an automated textile quality inspection system using YOLOv8 segmentation models. The system can detect, classify, and measure fabric defects in real-time, providing accurate quality control for textile manufacturing processes.

### Key Features

- Real-time fabric defect detection using YOLOv8 segmentation
- Calibration system for accurate dimensional measurements
- Database integration for defect tracking and analysis
- Support for multiple defect types and classifications
- Automated annotation saving for quality records
- Needle angle monitoring that detects a rotated camera, confirmed by re-checks
  before any alert is sent
- Retained MQTT camera calibration status (`invalid` / `valid`) and a remote
  command to clear it

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Camera Rotation and Calibration Status](#camera-rotation-and-calibration-status)
- [MQTT Topics](#mqtt-topics)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## Installation

### Prerequisites

- Python 3.11 or higher
- pip package manager
- Git

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/RishWijewardhena/vision-textile-inspection.git
   cd vision-textile-inspection
   ```

2. **Create a virtual environment**
   
   For Linux/macOS:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
   
   For Windows:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   
   Create a `.env` file in the root directory with your configuration settings (if needed).

## Usage

### Running the Calibration Tool

Before performing inspections, calibrate the system for accurate measurements:

```bash
python calibration.py
```

### Running the Main Inspection System

Start the fabric inspection application:

```bash
python main.py
```

### Database Management

Access database operations directly:

```bash
python database.py
```

### Running the Tests

```bash
python3 -m unittest discover -s tests
```

## Camera Rotation and Calibration Status

A background `NeedleAngleWorker` (`needle_angle_measure.py`) checks the needle
angle every `NEEDLE_ANGLE_CHECK_INTERVAL` seconds (30 min). If the needle is
outside `NEEDLE_NOT_ROTATED_ANGLE_MIN`–`NEEDLE_NOT_ROTATED_ANGLE_MAX`, the camera
is considered rotated and the extrinsic calibration is no longer trusted.

### Confirmation before alerting

A single rotated result is not reported, to avoid alerts from false detections:

1. The first rotated result schedules a re-check after `NEEDLE_RECHECK_DELAY`
   seconds (60 s).
2. Rotation is confirmed only after `NEEDLE_ROTATION_CONFIRM_COUNT` (3)
   consecutive rotated results, i.e. the first check plus two re-checks.
3. A re-check that finds the needle within range, or finds no needle, cancels the
   confirmation and nothing is sent.

Once confirmed:

- `rotated` is published on `camera_issue` every loop (not retained) until a
  check finds the needle within range again.
- `CalibrationMonitor` (`calibration_monitor.py`) saves the hash of
  `camera_extrinsics.json` to `camera_extrinsics_bad_hash.txt` (next to
  `main.py`) and publishes `invalid` (retained) on `camera_calibration_ex`.

### Clearing the calibration status

The status returns to `valid` in either of these ways:

- **Recalibrate:** a new extrinsic calibration changes `camera_extrinsics.json`.
  `CalibrationMonitor` compares the hash every 5 s, deletes the bad-hash file
  and publishes `valid`. Restart the service so the new extrinsics are used for
  measurements.
- **Clear command:** publish `clear` (**not retained**) to
  `machine/<DB_TABLE>/commands/clear_calibration`. The app deletes
  `camera_extrinsics_bad_hash.txt` through
  `scripts/clear_calibration_bad_hash.py`, resets its in-memory state and
  publishes `valid`. No restart is needed.

A retained `clear` command would be re-delivered on every reconnect, so always
send it without retain.

To delete the file by hand (takes effect after the next restart):

```bash
python3 scripts/clear_calibration_bad_hash.py
```

## MQTT Topics

All topics use `DB_TABLE` as the machine ID:

| Topic | Direction | Payload | Retained |
|---|---|---|---|
| `machine/<DB_TABLE>/status/heartbeat` | device → broker | `on` every `MQTT_HEARTBEAT_INTERVAL` s | no |
| `machine/<DB_TABLE>/commands/reset` | broker → device | `reset`; device replies `reset_success` | no |
| `machine/<DB_TABLE>/commands/clear_calibration` | broker → device | `clear` | no |
| `machine/<DB_TABLE>/status/esp32_issue` | device → broker | `issue` while the ESP32 is disconnected | no |
| `machine/<DB_TABLE>/status/camera_issue` | device → broker | `issue` while no camera frames arrive; `rotated` every loop while rotation is confirmed | no |
| `machine/<DB_TABLE>/status/marker_issue` | device → broker | `issue` when marker displacement exceeds the threshold | no |
| `machine/<DB_TABLE>/status/camera_calibration_ex` | device → broker | `invalid` / `valid` | yes (QoS 1) |

## Project Structure

```
Main_code/
├── .gitignore                # Git ignore rules
├── README.md                 # Project documentation
├── requirements.txt          # Python dependencies
├── calibration.py           # Camera calibration module
├── main.py                  # Main inspection application
├── database.py              # Database operations
├── yolov8n_seg_200.pt      # Pre-trained YOLO model Old
├── best_Model.pt           #re trained  model for angled camera mount 
├── __pycache__/             # Python cache (ignored)
├── .env/                    # Virtual environment (ignored)
└── saved_annotations/       # Annotation storage (ignored)
```

### Module Descriptions

- **calibration.py**: Handles camera calibration for accurate spatial measurements
- **main.py**: Core inspection logic and defect detection pipeline
- **database.py**: Database connectivity and data storage operations
- **needle_angle_measure.py**: Needle angle detection worker used to detect a rotated camera
- **calibration_monitor.py**: Tracks the extrinsics calibration status and publishes `invalid` / `valid`
- **mqtt_heartbeat.py**: MQTT heartbeat, status publishing and reset / clear calibration command listener
- **scripts/clear_calibration_bad_hash.py**: Deletes `camera_extrinsics_bad_hash.txt`; used by the clear calibration command and runnable by hand
- **best_Model.pt**: YOLOv8 nano segmentation model trained on textile defects

## Configuration

The system can be configured through environment variables or configuration files. Key parameters include:

- Camera resolution and frame rate
- Detection confidence threshold
- Model input size
- Database connection settings
- Calibration parameters
- Needle angle monitoring in `config.py`:
  - `NEEDLE_ANGLE_CHECK_INTERVAL`: seconds between needle angle checks
  - `NEEDLE_NOT_ROTATED_ANGLE_MIN`, `NEEDLE_NOT_ROTATED_ANGLE_MAX`: needle angle range treated as not rotated
  - `NEEDLE_ROTATION_CONFIRM_COUNT`, `NEEDLE_RECHECK_DELAY`: consecutive rotated checks required before alerting, and the delay between re-checks

## Dependencies

### Core Libraries

- **Python**: 3.11+
- **OpenCV**: Computer vision operations and image processing
- **NumPy**: Numerical computations and array operations
- **PyTorch**: Deep learning framework
- **Ultralytics**: YOLOv8 implementation

### Complete Dependency List

See `requirements.txt` for the full list of dependencies with version specifications.

## Model Information

The project uses a YOLOv8 medium segmentation model (`best_Model.pt`) trained specifically for detect the edge of the garment and the stitches of the garment. The model can identify and segment various types of fabric defects including:

- Stitches
- Marker which toches the garment edge


## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contact

**Rish Wijewardhena**

- GitHub: [@RishWijewardhena](https://github.com/RishWijewardhena)
- Project Link: [https://github.com/RishWijewardhena/vision-textile-inspection](https://github.com/RishWijewardhena/vision-textile-inspection)

## Acknowledgments

- YOLOv8 by Ultralytics
- OpenCV community
- PyTorch team

---

**Note**: This project is under active development. Features and documentation may be updated regularly.