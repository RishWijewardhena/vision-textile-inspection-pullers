"""
Camera extrinsics calibration monitor.

When the needle angle check reports the camera as rotated, the current extrinsics
file is marked as "bad" (its hash is persisted to disk) and "invalid" is published.
Once the extrinsics file changes (the user re-ran the extrinsics calibration),
"valid" is published and the persisted state is cleared.
"""
import hashlib
import os
import time
from datetime import datetime


def _ts():
    return datetime.now().strftime("[%H:%M:%S]")


def compute_file_hash(path):
    """Return a SHA-256 hash for a file, or None if it cannot be read (missing / mid-write)."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError as exc:
        print(_ts() + f" ⚠️ Failed to hash calibration file {path}: {exc}")
        return None
    return digest.hexdigest()


def read_calibration_hash_state(state_path):
    """Return the last known bad extrinsics hash saved on disk, if any."""
    try:
        if not os.path.exists(state_path):
            return None
        with open(state_path, "r", encoding="utf-8") as fh:
            value = fh.read().strip()
        return value or None
    except Exception as exc:
        print(_ts() + f" ⚠️ Failed to read calibration hash state: {exc}")
        return None


def write_calibration_hash_state(state_path, value):
    """Persist the last known bad extrinsics hash to disk."""
    try:
        with open(state_path, "w", encoding="utf-8") as fh:
            fh.write(str(value))
        return True
    except Exception as exc:
        print(_ts() + f" ⚠️ Failed to write calibration hash state: {exc}")
        return False


def clear_calibration_hash_state(state_path):
    """Remove the persisted hash when the calibration has been updated."""
    try:
        if os.path.exists(state_path):
            os.remove(state_path)
        return True
    except Exception as exc:
        print(_ts() + f" ⚠️ Failed to clear calibration hash state: {exc}")
        return False


class CalibrationMonitor:
    """Tracks whether the extrinsics calibration is valid and publishes state changes.

    publish: callable(state) -> bool, called with "invalid" or "valid". A failed
    publish is retried on the next poll().
    """

    def __init__(self, extrinsics_path, state_path, publish, check_interval_sec=5.0,
                 clock=time.monotonic, debug=False):
        self.extrinsics_path = extrinsics_path
        self.state_path = state_path
        self._publish = publish
        self.check_interval_sec = check_interval_sec
        self._clock = clock
        self.debug = debug

        self.bad_hash = read_calibration_hash_state(state_path)
        self._last_check_at = None
        # Re-send the retained state on startup in case it was never delivered before a restart
        self._unsent_state = "invalid" if self.bad_hash else None

        if debug:
            print(_ts(), f" Loaded saved bad calibration hash: {self.bad_hash or 'none'}")

    @property
    def invalid(self):
        return self.bad_hash is not None

    def on_rotated(self):
        """Call once per new angle result that reports the camera as rotated."""
        if self.invalid:
            return

        current_hash = compute_file_hash(self.extrinsics_path)
        if current_hash is None:
            return

        self.bad_hash = current_hash
        if not write_calibration_hash_state(self.state_path, current_hash):
            print(_ts(), "⚠️ Could not persist bad calibration hash to disk")
        self._unsent_state = "invalid"
        self._flush()

    def poll(self):
        """Call every loop iteration. Detects a new calibration and retries failed publishes."""
        self._flush()

        if not self.invalid:
            return

        now = self._clock()
        if self._last_check_at is not None and now - self._last_check_at < self.check_interval_sec:
            return
        self._last_check_at = now

        current_hash = compute_file_hash(self.extrinsics_path)
        if current_hash is None:
            return

        if self.debug:
            print(_ts(), f" Calibration compare: saved={self.bad_hash}, current={current_hash}")

        if current_hash == self.bad_hash:
            return

        print(_ts(), " ✅ Extrinsics calibration file changed; calibration marked valid")
        clear_calibration_hash_state(self.state_path)
        self.bad_hash = None
        self._unsent_state = "valid"
        self._flush()

    def clear(self):
        """Forget the bad hash in memory and publish "valid" (e.g. after the state file was deleted remotely)."""
        self.bad_hash = None
        self._last_check_at = None
        self._unsent_state = "valid"
        self._flush()

    def _flush(self):
        if self._unsent_state is None:
            return
        try:
            ok = self._publish(self._unsent_state)
        except Exception as exc:
            print(_ts() + f" ⚠️ MQTT camera calibration {self._unsent_state} publish failed: {exc}")
            ok = False
        if ok:
            self._unsent_state = None
