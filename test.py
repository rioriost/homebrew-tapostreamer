#!/usr/bin/env python3
"""
Unittests for tapostreamer.
We test primarily:
  • Window.create_grid using dummy frames.
  • CameraStreamThread (get_frame) using a dummy video capture.
  • Camera.is_valid_ip (a pure function).
  • Camera.scan_tcp_port by patching socket.socket.

Note: for functions that interact with external systems (e.g. ARP,
keyring, cv2.VideoCapture etc.) we monkey-patch or create dummy objects.
"""

import unittest
import numpy as np
import time
import os
import sys

from unittest.mock import patch, MagicMock

# Import the classes and methods from your module.
# Adjust the import depending on how you package your code.
# In this example we assume the module is named tapostreamer.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from tapostreamer.main import CameraStreamThread, Window, Camera


# Dummy video capture class to simulate cv2.VideoCapture
class DummyVideoCapture:
    def __init__(self, url):
        self.url = url
        self.opened = True
        self.call_count = 0

    def isOpened(self):
        return self.opened

    def read(self):
        # simulate returning a dummy frame.
        # Create a dummy frame based on the url: a 3-channel uint8 image.
        self.call_count += 1
        # for testing, generate a dummy image with each pixel value as call_count mod 256
        height, width, channels = 360, 640, 3
        frame = np.full(
            (height, width, channels), self.call_count % 256, dtype=np.uint8
        )
        return True, frame

    def release(self):
        self.opened = False


# Patch cv2.VideoCapture so that our thread uses the dummy instead
def dummy_video_capture_constructor(url):
    return DummyVideoCapture(url)


class TestWindow(unittest.TestCase):
    def setUp(self):
        # Create dummy frames; use Window.DEFAULT_FRAME_SIZE for size.
        self.frame_size = Window.DEFAULT_FRAME_SIZE
        # create two dummy frames (e.g., one zero image, one one image)
        self.frame_zero = np.zeros(self.frame_size, dtype=np.uint8)
        self.frame_one = np.ones(self.frame_size, dtype=np.uint8) * 255
        # Create a Window instance with dummy credentials, layout, and cameras.
        dummy_layout = {"row": 2, "col": 2}
        dummy_cameras = {
            "cam1": "192.168.1.10",
            "cam2": "192.168.1.11",
            "cam3": "192.168.1.12",
            "cam4": "192.168.1.13",
        }
        self.window = Window("dummy", "dummy", dummy_layout, dummy_cameras)

    def test_create_grid(self):
        # Create a list of four frames (2 rows x 2 columns)
        frames = [self.frame_zero, self.frame_one, self.frame_one, self.frame_zero]
        grid = self.window.create_grid(frames, rows=2, cols=2)
        expected_height = Window.DEFAULT_FRAME_SIZE[0] * 2
        expected_width = Window.DEFAULT_FRAME_SIZE[1] * 2
        self.assertEqual(
            grid.shape, (expected_height, expected_width, Window.DEFAULT_FRAME_SIZE[2])
        )

    def test_get_frames_returns_correct_number(self):
        # Set up dummy CameraStreamThreads in the window.
        # Instead of real threads, add dummy objects with get_frame.
        class DummyThread:
            def get_frame(self):
                return self.frame

        # Create dummy threads that returns a specific frame
        dummy_thread1 = DummyThread()
        dummy_thread1.frame = self.frame_zero
        dummy_thread2 = DummyThread()
        dummy_thread2.frame = self.frame_one

        self.window.stream_threads = [dummy_thread1, dummy_thread2]
        frames = self.window.get_frames()
        self.assertEqual(len(frames), 2)
        # Check that the frame contents match what our dummies hold.
        self.assertTrue(np.array_equal(frames[0], self.frame_zero))
        self.assertTrue(np.array_equal(frames[1], self.frame_one))


class TestCameraStreamThread(unittest.TestCase):
    def setUp(self):
        # Use patch to have cv2.VideoCapture return our dummy capture object
        patcher = patch(
            "tapostreamer.main.cv2.VideoCapture",
            side_effect=dummy_video_capture_constructor,
        )
        self.addCleanup(patcher.stop)
        self.mock_VideoCapture = patcher.start()

        self.frame_size = (360, 640, 3)
        self.default_frame = np.zeros(self.frame_size, dtype=np.uint8)
        self.url = "dummy_url"

        # Create a CameraStreamThread instance.
        self.thread = CameraStreamThread(self.url, self.default_frame, self.frame_size)
        # Start the thread.
        self.thread.start()
        # Allow some time for the thread to run and update the frame.
        time.sleep(0.05)

    def tearDown(self):
        self.thread.stop()
        self.thread.join(timeout=1)

    def test_get_frame(self):
        # Get a frame from the thread, and check its shape.
        frame = self.thread.get_frame()
        self.assertEqual(frame.shape, self.frame_size)

    def test_thread_updates_frame(self):
        # Call get_frame several times and ensure that the frame changes (because dummy returns incrementing values)
        frame1 = self.thread.get_frame()
        time.sleep(0.02)
        frame2 = self.thread.get_frame()
        # Since our dummy capture returns a frame with increasing call_count, they should differ.
        self.assertFalse(np.array_equal(frame1, frame2))


class TestCameraUtilities(unittest.TestCase):
    def test_is_valid_ip_valid(self):
        # Test valid IP address
        self.assertTrue(Camera.is_valid_ip("192.168.1.100"))
        self.assertTrue(Camera.is_valid_ip("127.0.0.1"))

    def test_is_valid_ip_invalid(self):
        # Test an invalid IP address (each octet should be 0-255)
        self.assertFalse(Camera.is_valid_ip("999.999.999.999"))
        self.assertFalse(Camera.is_valid_ip("abcd"))

    def test_is_valid_ip_hostname(self):
        # Depending on the system, 'localhost' should resolve to valid IP.
        # We assume that localhost resolving to 127.0.0.1 makes it valid.
        self.assertTrue(Camera.is_valid_ip("localhost"))

    @patch("tapostreamer.main.socket.socket")
    def test_scan_tcp_port_success(self, mock_socket_cls):
        # Set up the mock socket (simulate port open)
        instance = MagicMock()
        instance.connect_ex.return_value = 0  # simulate successful connect
        mock_socket_cls.return_value = instance

        self.assertTrue(Camera.scan_tcp_port("192.168.1.100", port_num=554, timeout=1))
        instance.connect_ex.assert_called_with(("192.168.1.100", 554))

    @patch("tapostreamer.main.socket.socket")
    def test_scan_tcp_port_failure(self, mock_socket_cls):
        # Set up the mock socket (simulate port closed)
        instance = MagicMock()
        instance.connect_ex.return_value = 1  # nonzero means failure
        mock_socket_cls.return_value = instance

        self.assertFalse(Camera.scan_tcp_port("192.168.1.101", port_num=554, timeout=1))
        instance.connect_ex.assert_called_with(("192.168.1.101", 554))


if __name__ == "__main__":
    unittest.main()
