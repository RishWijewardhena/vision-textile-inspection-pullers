import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibration_monitor import CalibrationMonitor


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakePublisher:
    def __init__(self):
        self.sent = []
        self.fail = False

    def __call__(self, state):
        if self.fail:
            return False
        self.sent.append(state)
        return True


class CalibrationMonitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.extr = os.path.join(self.tmp.name, "camera_extrinsics.json")
        self.state = os.path.join(self.tmp.name, "camera_extrinsics_bad_hash.txt")
        self.write_extrinsics('{"v": 1}')
        self.clock = FakeClock()
        self.pub = FakePublisher()

    def tearDown(self):
        self.tmp.cleanup()

    def write_extrinsics(self, content):
        with open(self.extr, "w") as fh:
            fh.write(content)

    def make_monitor(self):
        return CalibrationMonitor(self.extr, self.state, self.pub, check_interval_sec=5.0, clock=self.clock)

    def advance(self, seconds=5.0):
        self.clock.now += seconds

    def test_rotated_publishes_invalid_once(self):
        m = self.make_monitor()
        for _ in range(10):
            m.on_rotated()
            m.poll()
            self.advance()
        self.assertEqual(self.pub.sent, ["invalid"])
        self.assertTrue(os.path.exists(self.state))

    def test_recalibration_while_rotated_is_still_detected(self):
        m = self.make_monitor()
        m.on_rotated()
        self.write_extrinsics('{"v": 2}')
        m.on_rotated()  # stale "rotated" result must not absorb the new calibration
        self.advance()
        m.poll()
        self.assertEqual(self.pub.sent, ["invalid", "valid"])
        self.assertFalse(m.invalid)
        self.assertFalse(os.path.exists(self.state))

    def test_rotated_again_after_valid_publishes_invalid(self):
        m = self.make_monitor()
        m.on_rotated()
        self.write_extrinsics('{"v": 2}')
        m.poll()
        m.on_rotated()
        self.assertEqual(self.pub.sent, ["invalid", "valid", "invalid"])

    def test_restart_with_unchanged_file_stays_invalid(self):
        self.make_monitor().on_rotated()
        self.pub.sent.clear()
        m = self.make_monitor()
        m.poll()
        self.advance()
        m.poll()
        self.assertTrue(m.invalid)
        self.assertEqual(self.pub.sent, ["invalid"])  # retained state re-sent once on startup

    def test_restart_with_changed_file_publishes_valid(self):
        self.make_monitor().on_rotated()
        self.pub.sent.clear()
        self.write_extrinsics('{"v": 2}')
        m = self.make_monitor()
        m.poll()
        self.assertFalse(m.invalid)
        self.assertEqual(self.pub.sent[-1], "valid")

    def test_missing_file_does_not_crash_or_change_state(self):
        m = self.make_monitor()
        os.remove(self.extr)
        m.on_rotated()
        self.assertFalse(m.invalid)
        self.write_extrinsics('{"v": 1}')
        m.on_rotated()
        os.remove(self.extr)
        self.advance()
        m.poll()
        self.assertTrue(m.invalid)
        self.assertEqual(self.pub.sent, ["invalid"])

    def test_failed_publish_is_retried(self):
        m = self.make_monitor()
        self.pub.fail = True
        m.on_rotated()
        self.assertEqual(self.pub.sent, [])
        self.pub.fail = False
        m.poll()
        self.assertEqual(self.pub.sent, ["invalid"])

    def test_hash_check_is_throttled(self):
        m = self.make_monitor()
        m.on_rotated()
        m.poll()
        self.write_extrinsics('{"v": 2}')
        self.advance(1.0)
        m.poll()
        self.assertTrue(m.invalid)
        self.advance(5.0)
        m.poll()
        self.assertFalse(m.invalid)


if __name__ == "__main__":
    unittest.main()
