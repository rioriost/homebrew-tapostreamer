from tapostreamer import Camera, UserCredential, Utility, Window

import pathlib
from typing import Optional
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np


class FakeCapture:
    def __init__(self, frame: Optional[np.ndarray], ret: bool = True) -> None:
        self.frame = frame
        self.ret = ret

    def read(self) -> tuple:
        return self.ret, self.frame

    def release(self) -> None:
        pass


class TestWindow(unittest.TestCase):
    def test_get_frames_all_success(self) -> None:
        # ダミーのフレーム（全画素255の画像）を用意
        dummy_frame = np.ones(Window.DEFAULT_FRAME_SIZE, dtype=np.uint8) * 255
        # FakeCapture のインスタンス（read()で成功を返す）
        cap1 = FakeCapture(dummy_frame, ret=True)
        cap2 = FakeCapture(dummy_frame, ret=True)
        # Window インスタンスはレイアウト、カメラ情報は任意
        window = Window(
            "dummy",
            "dummy",
            {"row": 1, "col": 2},
            {"camera1": "192.168.1.10", "camera2": "192.168.1.11"},
        )
        frames = window.get_frames([cap1, cap2])
        self.assertEqual(len(frames), 2)
        # cv2.resize されるため、同じサイズであることを確認
        expected = cv2.resize(
            dummy_frame, (Window.DEFAULT_FRAME_SIZE[1], Window.DEFAULT_FRAME_SIZE[0])
        )
        for frame in frames:
            self.assertTrue((frame == expected).all())

    def test_get_frames_failure(self) -> None:
        # read() が失敗した場合は全零のフレームが返るはず
        cap_fail = FakeCapture(None, ret=False)
        window = Window(
            "dummy", "dummy", {"row": 1, "col": 1}, {"camera1": "192.168.1.10"}
        )
        frames = window.get_frames([cap_fail])
        self.assertEqual(len(frames), 1)
        self.assertTrue(
            (frames[0] == np.zeros(Window.DEFAULT_FRAME_SIZE, dtype=np.uint8)).all()
        )

    def test_create_grid(self) -> None:
        # 2 x 2 のグリッド生成テスト
        frame = np.full(Window.DEFAULT_FRAME_SIZE, 100, dtype=np.uint8)
        frames = [frame] * 4
        window = Window(
            "dummy", "dummy", {"row": 2, "col": 2}, {"camera1": "192.168.1.10"}
        )
        grid = window.create_grid(frames, 2, 2)
        expected_shape = (
            Window.DEFAULT_FRAME_SIZE[0] * 2,
            Window.DEFAULT_FRAME_SIZE[1] * 2,
            3,
        )
        self.assertEqual(grid.shape, expected_shape)


class TestCamera(unittest.TestCase):
    def test_is_valid_ip_valid(self) -> None:
        self.assertTrue(Camera.is_valid_ip("192.168.1.1"))

    def test_is_valid_ip_invalid(self) -> None:
        self.assertFalse(Camera.is_valid_ip("999.999.999.999"))
        self.assertFalse(Camera.is_valid_ip("invalidhost"))

    @patch("subprocess.check_output")
    def test_get_arp_ip_list(self, mock_check_output: unittest.mock.MagicMock) -> None:
        dummy_output = (
            "Interface: 192.168.1.1 --- 0x3\n"
            "  Internet Address      Physical Address      Type\n"
            "  (192.168.1.10)       xx-xx-xx-xx-xx-xx     dynamic\n"
        )
        mock_check_output.return_value = dummy_output.encode("utf-8")
        ip_list = Camera.get_arp_ip_address_list()
        self.assertIn("192.168.1.10", ip_list)

    @patch("socket.socket")
    def test_scan_tcp_port_success(
        self, mock_socket_class: unittest.mock.MagicMock
    ) -> None:
        # connect_ex が 0 を返すなら接続成功
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_socket_class.return_value = mock_sock
        self.assertTrue(Camera.scan_tcp_port("192.168.1.10"))

    @patch("socket.socket")
    def test_scan_tcp_port_failure(
        self, mock_socket_class: unittest.mock.MagicMock
    ) -> None:
        # connect_ex が 0 以外なら失敗
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 1
        mock_socket_class.return_value = mock_sock
        self.assertFalse(Camera.scan_tcp_port("192.168.1.10"))

    @patch("builtins.input", side_effect=["0"])
    def test_select_skip(self, mock_input: unittest.mock.MagicMock) -> None:
        cam = Camera()
        # Utility.exit_program をモック化してシステム終了しないようにする
        with patch.object(Utility, "exit_program"):
            # 第一候補でスキップ（"0" 入力）させるテスト
            result = cam.select(["192.168.1.10", "192.168.1.11"])
            self.assertEqual(result, "")

    def test_load_config(self) -> None:
        # 一時ディレクトリを利用して config 読み込みの動作確認
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdirname:
            cam = Camera(init=False)
            cam.config_path = pathlib.Path(tmpdirname) / "config.ini"
            # ダミーの設定ファイルを作成
            cam.config["LAYOUT"] = {"row": "2", "col": "3"}
            cam.config["CAMERAS"] = {
                "camera0-0": "192.168.1.10",
                "camera0-1": "",
                "camera0-2": "",
            }
            with open(cam.config_path, "w") as f:
                cam.config.write(f)
            cam.load_config()
            self.assertEqual(cam.layout, {"row": 2, "col": 3})
            self.assertEqual(
                cam.cameras,
                {"camera0-0": "192.168.1.10", "camera0-1": "", "camera0-2": ""},
            )


class TestUserCredential(unittest.TestCase):
    @patch("keyring.get_password", return_value="dummy")
    @patch("keyring.set_password")
    @patch("builtins.input", side_effect=["dummy", "dummy"])
    def test_ensure_credentials_already_set(
        self,
        mock_input: unittest.mock.MagicMock,
        mock_set: unittest.mock.MagicMock,
        mock_get: unittest.mock.MagicMock,
    ) -> None:
        creds = UserCredential(init=False)
        self.assertEqual(creds.user_id, "dummy")
        self.assertEqual(creds.user_pw, "dummy")

    @patch("keyring.get_password", side_effect=[None, None, "user", "pass"])
    @patch("keyring.set_password")
    @patch("builtins.input", side_effect=["user", "pass"])
    def test_ensure_credentials_input(
        self,
        mock_input: unittest.mock.MagicMock,
        mock_set: unittest.mock.MagicMock,
        mock_get: unittest.mock.MagicMock,
    ) -> None:
        creds = UserCredential(init=False)
        self.assertEqual(creds.user_id, "user")
        self.assertEqual(creds.user_pw, "pass")


class TestUtility(unittest.TestCase):
    def test_exit_program(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            Utility.exit_program()
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
