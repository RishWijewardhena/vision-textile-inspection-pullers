"""Background cleanup for old captured annotation files."""

import os
import threading
import time
from datetime import datetime, timedelta

from config import FILE_CLEANUP_INTERVAL_SECONDS, FILE_RETENTION_HOURS, SAVE_DIR


class FileCleanerThread:
    def __init__(
        self,
        directory=SAVE_DIR,
        retention_hours=FILE_RETENTION_HOURS,
        check_interval=FILE_CLEANUP_INTERVAL_SECONDS,
    ):
        """Initialize file cleaner settings."""
        self.directory = directory
        self.retention_hours = retention_hours
        self.check_interval = check_interval
        self.running = False
        self.thread = None

        print(
            "File cleaner initialized: "
            f"directory={directory}, retention={retention_hours}h, interval={check_interval}s"
        )

    def _delete_old_files(self):
        """Delete files older than retention period (recursive)."""
        if not os.path.exists(self.directory):
            print(f"Cleanup skipped: directory not found -> {self.directory}")
            return

        cutoff_time = datetime.now() - timedelta(hours=self.retention_hours)
        deleted_files = 0
        deleted_bytes = 0

        try:
            # Walk bottom-up so empty folders can be removed after file cleanup.
            for root, _, files in os.walk(self.directory, topdown=False):
                for filename in files:
                    file_path = os.path.join(root, filename)

                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    except OSError as exc:
                        print(f"Could not read mtime for {file_path}: {exc}")
                        continue

                    if mtime < cutoff_time:
                        try:
                            file_size = os.path.getsize(file_path)
                            os.remove(file_path)
                            deleted_files += 1
                            deleted_bytes += file_size
                            print(f"Deleted old file: {file_path}")
                        except OSError as exc:
                            print(f"Failed deleting {file_path}: {exc}")

                # Remove empty session directories except root SAVE_DIR itself.
                if root != self.directory:
                    try:
                        if not os.listdir(root):
                            os.rmdir(root)
                            print(f"Removed empty folder: {root}")
                    except OSError:
                        # Ignore non-empty or race-condition errors.
                        pass

            if deleted_files:
                freed_mb = deleted_bytes / (1024 * 1024)
                print(f"Cleanup complete: {deleted_files} files removed, {freed_mb:.2f} MB freed")
            else:
                print("Cleanup complete: no files older than retention window")
        except Exception as exc:
            print(f"Cleanup error: {exc}")

    def _cleanup_loop(self):
        """Run cleanup periodically in a daemon thread."""
        while self.running:
            self._delete_old_files()

            # Sleep in small steps for responsive shutdown.
            for _ in range(self.check_interval):
                if not self.running:
                    break
                time.sleep(1)

        print("File cleaner thread stopped")

    def start(self):
        """Start the cleanup thread."""
        if self.running:
            print("File cleaner is already running")
            return False

        self.running = True
        self.thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.thread.start()
        print("File cleaner thread started")
        return True

    def stop(self):
        """Stop the cleanup thread."""
        if not self.running:
            print("File cleaner is not running")
            return False

        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=5)
            self.thread = None

        print("File cleaner stopped")
        return True

    def force_cleanup(self):
        """Run cleanup once immediately."""
        self._delete_old_files()


if __name__ == "__main__":
    cleaner = FileCleanerThread()
    cleaner.start()
    try:
        print("File cleaner is running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleaner.stop()