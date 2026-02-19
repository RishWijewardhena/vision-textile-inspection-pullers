# measurement.py
import os
import json
import cv2
import numpy as np
from collections import deque
from ultralytics import YOLO
import time
from datetime import datetime

from config import *

# -------------------------
# Helper Functions
# -------------------------
def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def force_camera_resolution(cap, w, h):
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    time.sleep(2)
    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, CAMERA_AUTO_EXPOSURE)
    cap.set(cv2.CAP_PROP_EXPOSURE, CAMERA_EXPOSURE)
    if aw != w or ah != h:
        print(f"Warning: camera resolution {aw}x{ah}, expected {w}x{h}")
    return aw, ah

def compute_camera_plane(R, t):
    n_c = R[:, 2].astype(np.float64)
    d_c = -float(n_c.dot(t))
    return n_c, d_c

def pixel_to_world(u, v, K, dist, R, t, n_c, d_c):
    """Convert pixel (u,v) to 3D world point via ray-plane intersection."""
    try:
        und = cv2.undistortPoints(np.array([[[float(u), float(v)]]], dtype=np.float64), K, dist, P=None)
        d_cam = np.array([float(und[0,0,0]), float(und[0,0,1]), 1.0], dtype=np.float64)
        denom = float(n_c.dot(d_cam))
        if abs(denom) < 1e-9:
            return None
        X_cam = (-d_c / denom) * d_cam
        return R.T.dot(X_cam - t)
    except Exception:
        return None

def get_mask(result, idx, h, w):
    """Extract binary instance mask from YOLO result."""
    try:
        arr = result.masks.data[idx].cpu().numpy()
        if arr.shape != (h, w):
            arr = cv2.resize(arr, (w, h), interpolation=cv2.INTER_NEAREST)
        mask = (arr > 0).astype(np.uint8)
        return mask if np.count_nonzero(mask) > 0 else None
    except Exception:
        return None

def marker_far_edge_envelope(marker_mask):
    """Return topmost (far-from-camera) marker pixel y per column; -1 if absent."""
    has_any = marker_mask.any(axis=0)
    idx_top = np.argmax(marker_mask > 0, axis=0)
    return np.where(has_any, idx_top, -1).astype(int)

def kmeans_1d_two_clusters(values, max_iters=10):
    """1D k-means with k=2. Returns (labels, (center0, center1))."""
    if values.size < 2:
        return np.zeros(values.shape[0], dtype=int), (float(values.mean()), float(values.mean()))
    c0, c1 = float(values.min()), float(values.max())
    labels = np.zeros(values.shape[0], dtype=int)
    for _ in range(max_iters):
        new_labels = (np.abs(values - c1) < np.abs(values - c0)).astype(int)
        if new_labels.sum() == 0 or new_labels.sum() == len(values):
            break
        new_c0 = float(values[new_labels == 0].mean()) if (new_labels == 0).any() else c0
        new_c1 = float(values[new_labels == 1].mean()) if (new_labels == 1).any() else c1
        if new_c0 == c0 and new_c1 == c1:
            break
        c0, c1, labels = new_c0, new_c1, new_labels
    return labels, (c0, c1)

# -------------------------
# Stitch Measurement Application
# -------------------------
class StitchMeasurementApp:
    """Detects stitches and marker, measures seam allowance and stitch width."""

    def __init__(self, calib_path, extr_path, model_path, camera_index=0,
                 calib_w=640, calib_h=640, frame_buffer=FRAME_BUFFER,
                 min_stitches=MIN_STITCHES, stitch_id=STITCH_CLASS_ID,
                 marker_id=MARKER_CLASS_ID):
        if not os.path.exists(calib_path):
            raise FileNotFoundError(f"Calibration file missing: {calib_path}")
        calib = load_json(calib_path)
        self.K    = np.array(calib["camera_matrix"], dtype=np.float64)
        self.dist = np.array(calib["dist_coeffs"], dtype=np.float64).ravel()

        if not os.path.exists(extr_path):
            raise FileNotFoundError(f"Extrinsics file missing: {extr_path}")
        extr = load_json(extr_path)
        R_mat, _ = cv2.Rodrigues(np.array(extr["rvec"], dtype=np.float64).reshape(3, 1))
        self.R = R_mat
        self.t = np.array(extr["tvec"], dtype=np.float64).reshape(3,)
        self.n_c, self.d_c = compute_camera_plane(self.R, self.t)

        self.model = YOLO(model_path)
        self.cap   = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        self.aw, self.ah = force_camera_resolution(self.cap, calib_w, calib_h)

        self.frame_buf_dist  = deque(maxlen=frame_buffer)
        self.frame_buf_width = deque(maxlen=frame_buffer)
        self.min_stitches = min_stitches
        self.stitch_id    = stitch_id
        self.marker_id    = marker_id
        self.running      = True

        print("StitchMeasurementApp initialized.")
        if LOG_DEBUG:
            print("Plane normal:", self.n_c, "d_c:", self.d_c)

    def process_frame(self, frame):
        h, w = frame.shape[:2]

        # Fixed ROI band (sections ROI_SECTION_START to ROI_SECTION_END of ROI_SECTIONS)
        section_h = h / ROI_SECTIONS
        roi_y_min = int(ROI_SECTION_START * section_h)
        roi_y_max = int(ROI_SECTION_END   * section_h)

        try:
            results = self.model.predict(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                                         verbose=False, conf=CONF_THRESH,
                                         iou=IOU_THRESH, max_det=MAX_DETECTIONS)
            r = results[0]
        except Exception as e:
            print("Model inference error:", e)
            return frame.copy(), {'edge_distance_mm': None, 'stitch_width_mm': None,
                                  'stitch_count': 0, 'timestamp': datetime.now()}

        annotated = frame.copy()

        # Draw ROI band
        roi_overlay = annotated.copy()
        cv2.rectangle(roi_overlay, (0, roi_y_min), (w, roi_y_max), (0, 255, 255), -1)
        cv2.addWeighted(roi_overlay, 0.15, annotated, 0.85, 0, annotated)
        cv2.rectangle(annotated, (0, roi_y_min), (w, roi_y_max), (0, 255, 255), 2)
        cv2.putText(annotated, "ROI", (10, roi_y_min + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        stitch_masks, stitch_boxes, marker_masks = [], [], []

        if hasattr(r, "boxes") and r.boxes is not None:
            try:
                cls_arr = r.boxes.cls.cpu().numpy()
                boxes   = r.boxes.xyxy.cpu().numpy()
            except Exception:
                cls_arr, boxes = [], []

            for i, cls_id in enumerate(cls_arr):
                cid = int(cls_id)
                x1, y1, x2, y2 = map(int, boxes[i])
                mask = get_mask(r, i, h, w)

                if cid == self.stitch_id:
                    # Accept only stitches whose bbox centroid is inside the ROI band
                    cy_bbox = (y1 + y2) / 2.0
                    if roi_y_min < cy_bbox < roi_y_max:
                        stitch_masks.append(mask)
                        stitch_boxes.append((x1, y1, x2, y2))
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 255, 0), 1)
                    else:
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), (100, 100, 100), 1)

                elif cid == self.marker_id:
                    if mask is not None:
                        marker_masks.append(mask)
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 0, 255), 2)

        if LOG_DEBUG:
            print(f"Stitches in ROI: {len(stitch_masks)}, Markers: {len(marker_masks)}")

        # Combine marker masks
        marker_combined = None
        if marker_masks:
            combined = np.zeros((h, w), dtype=np.uint8)
            for m in marker_masks:
                if m is not None and m.shape == (h, w):
                    combined = cv2.bitwise_or(combined, m)
            if np.count_nonzero(combined) > 0:
                marker_combined = combined

        if marker_combined is None:
            cv2.putText(annotated, "Marker is not detected", (10, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return annotated, {'edge_distance_mm': None, 'stitch_width_mm': None,
                                'stitch_count': 0, 'timestamp': datetime.now()}

        envelope = marker_far_edge_envelope(marker_combined)

        # Draw marker far-edge envelope (orange) and contour
        env_pts = [(x, envelope[x]) for x in range(w) if envelope[x] >= 0]
        if env_pts:
            step = max(1, len(env_pts) // 1000)
            cv2.polylines(annotated, [np.array(env_pts[::step], dtype=np.int32)],
                          False, (0, 165, 255), 2)
        contours, _ = cv2.findContours((marker_combined > 0).astype(np.uint8),
                                       cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            cv2.drawContours(annotated, contours, -1, (0, 0, 255), 2)

        if len(stitch_masks) == 0:
            cv2.putText(annotated, "No stitches in ROI", (10, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return annotated, {'edge_distance_mm': None, 'stitch_width_mm': None,
                                'stitch_count': 0, 'timestamp': datetime.now()}

        # If there are 2 rows of stitches, keep only the row with the higher y
        # (closer to the marker edge = bottom of stitch region in image coords).
        centroids_y = []
        for idx, mask in enumerate(stitch_masks):
            x1, y1, x2, y2 = stitch_boxes[idx]
            if mask is not None and mask.sum() > 0:
                M = cv2.moments(mask)
                cy = float(M["m01"] / M["m00"]) if M["m00"] != 0 else (y1 + y2) / 2.0
            else:
                cy = (y1 + y2) / 2.0
            centroids_y.append(cy)

        active_indices = list(range(len(stitch_masks)))
        if len(centroids_y) >= 2:
            vals = np.array(centroids_y)
            labels, (c0, c1) = kmeans_1d_two_clusters(vals)
            # Pick the cluster with the higher mean y (lower in image = closer to marker)
            chosen_label = 0 if c0 > c1 else 1
            active_indices = [i for i, lab in enumerate(labels) if lab == chosen_label]
            if LOG_DEBUG:
                print(f"Clustering: c0={c0:.1f} c1={c1:.1f} → chose label {chosen_label} ({len(active_indices)} stitches)")

        # Measure each stitch in the selected row
        per_dists, per_widths = [], []

        for idx in active_indices:
            mask = stitch_masks[idx]
            x1, y1, x2, y2 = stitch_boxes[idx]

            # Centroid and horizontal extent from mask or bbox
            if mask is not None and mask.sum() > 0:
                M = cv2.moments(mask)
                if M["m00"] != 0:
                    cx, cy = float(M["m10"] / M["m00"]), float(M["m01"] / M["m00"])
                else:
                    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                cols = np.where(mask.any(axis=0))[0]
                left_px  = float(cols.min()) if cols.size > 0 else float(x1)
                right_px = float(cols.max()) if cols.size > 0 else float(x2)
            else:
                cx, cy   = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                left_px, right_px = float(x1), float(x2)

            cx_int = int(np.clip(round(cx), 0, w - 1))

            # Seam allowance: stitch centroid → marker far edge at same x
            xs = [int(np.clip(cx_int + dx, 0, w - 1))
                  for dx in range(-ENVELOPE_NEIGHBORHOOD, ENVELOPE_NEIGHBORHOOD + 1)]
            env_vals = [envelope[x] for x in xs if envelope[x] >= 0]
            if env_vals:
                edge_y  = float(np.median(env_vals))
                p_stitch = pixel_to_world(cx, cy,     self.K, self.dist, self.R, self.t, self.n_c, self.d_c)
                p_edge   = pixel_to_world(cx, edge_y, self.K, self.dist, self.R, self.t, self.n_c, self.d_c)
                if p_stitch is not None and p_edge is not None:
                    per_dists.append(float(np.linalg.norm(p_stitch - p_edge)) * 1000.0)
                    cv2.line(annotated, (cx_int, int(round(edge_y))),
                             (int(round(cx)), int(round(cy))), (0, 255, 0), 1)
                    cv2.circle(annotated, (cx_int, int(round(edge_y))), 3, (255, 0, 255), -1)

            # Stitch width: left → right edge
            p_left  = pixel_to_world(left_px,  cy, self.K, self.dist, self.R, self.t, self.n_c, self.d_c)
            p_right = pixel_to_world(right_px, cy, self.K, self.dist, self.R, self.t, self.n_c, self.d_c)
            if p_left is not None and p_right is not None:
                width_mm = float(np.linalg.norm(p_right - p_left)) * 1000.0
                per_widths.append(width_mm)
                cv2.line(annotated,
                         (int(round(left_px)), int(round(cy))),
                         (int(round(right_px)), int(round(cy))), (200, 200, 0), 1)
                cv2.circle(annotated, (int(round(left_px)),  int(round(cy))), 3, (200, 200, 0), -1)
                cv2.circle(annotated, (int(round(right_px)), int(round(cy))), 3, (200, 200, 0), -1)
                cv2.putText(annotated, f"w:{width_mm:.1f}mm",
                            (int(round(cx)) + 6, int(round(cy)) + 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

            cv2.circle(annotated, (int(round(cx)), int(round(cy))), 8, (255, 0, 0), -1)

        n_found = len(active_indices)

        # Temporal smoothing
        if len(per_dists) >= self.min_stitches:
            self.frame_buf_dist.append(float(np.mean(per_dists)))
            smooth_dist = float(np.median(self.frame_buf_dist))
        else:
            smooth_dist = None

        if len(per_widths) >= self.min_stitches:
            self.frame_buf_width.append(float(np.mean(per_widths)))
            smooth_width = float(np.median(self.frame_buf_width))
        else:
            smooth_width = None

        if smooth_dist is not None and smooth_width is not None:
            info = f"Seam: {smooth_dist:.2f}mm | Width: {smooth_width:.2f}mm (n={n_found})"
        elif smooth_dist is not None:
            info = f"Seam: {smooth_dist:.2f}mm (n={n_found})"
        elif smooth_width is not None:
            info = f"Width: {smooth_width:.2f}mm (n={n_found})"
        else:
            info = f"Insufficient stitches (found {n_found}, need {self.min_stitches})"

        cv2.putText(annotated, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(annotated, f"Stitches: {n_found} | Markers: {len(marker_masks)}",
                    (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        return annotated, {
            'edge_distance_mm': smooth_dist,
            'stitch_width_mm':  smooth_width,
            'stitch_count':     n_found,
            'timestamp':        datetime.now()
        }

    def get_single_measurement(self):
        ret, frame = self.cap.read()
        if not ret:
            return None, None
        return self.process_frame(frame)

    def run(self):
        """Continuous capture loop for standalone operation."""
        last_inference_time = 0
        frame_count = 0
        os.makedirs(SAVE_DIR, exist_ok=True)
        print(f"Saving to: {os.path.abspath(SAVE_DIR)}")

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                print("No frame, retrying...")
                continue

            current_time = time.time()
            if current_time - last_inference_time >= INFERENCE_INTERVAL:
                annotated, measurements = self.process_frame(frame)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join(SAVE_DIR, f"frame_{frame_count:05d}_{timestamp}.jpg")
                cv2.imwrite(save_path, annotated)
                print(f"Saved: {save_path} | Seam: {measurements.get('edge_distance_mm','N/A')}mm "
                      f"| Width: {measurements.get('stitch_width_mm','N/A')}mm")
                if SHOW_WINDOWS:
                    cv2.imshow("Stitch Measurement", annotated)
                last_inference_time = current_time
                frame_count += 1
            else:
                if SHOW_WINDOWS:
                    cv2.imshow("Stitch Measurement", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        self.cap.release()
        cv2.destroyAllWindows()
        print(f"\nTotal frames saved: {frame_count}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app = StitchMeasurementApp(
        calib_path=os.path.join(base_dir, INTRINSICS_FILE),
        extr_path=os.path.join(base_dir, EXTRINSICS_FILE),
        model_path=MODEL_PATH,
        camera_index=CAMERA_INDEX,
        calib_w=CALIB_W, calib_h=CALIB_H,
    )
    app.run()