import argparse
import configparser
import ipaddress
import pathlib
import re
import readline
import socket
import subprocess
import sys
import time
import threading
from importlib.metadata import version

import cv2
import keyring
import numpy as np


# Application Name
APP_NAME = "TapoStreamer"
__version__ = version("tapostreamer")


class CameraStreamThread(threading.Thread):
    def __init__(self, url: str, default_frame: np.ndarray, frame_size: tuple):
        super().__init__(daemon=True)
        self.url = url
        # create VideoCapture instance to be used in separate thread
        self.capture = cv2.VideoCapture(url)
        self.frame = default_frame.copy()  # hold the latest frame
        self.frame_size = frame_size  # (height, width, channel)
        self.stopped = False
        self.lock = threading.Lock()

    def run(self):
        while not self.stopped:
            # reconnect if capture is closed during operation
            if not self.capture.isOpened():
                print(
                    f"[WARN] Thread for {self.url} finds capture closed. Reconnecting..."
                )
                self.capture.release()
                time.sleep(0.5)
                self.capture = cv2.VideoCapture(self.url)
            try:
                ret, frame = self.capture.read()
            except Exception as e:
                print(f"[ERROR] Exception in thread reading {self.url}: {e}")
                ret = False
            if ret and frame is not None:
                try:
                    resized = cv2.resize(
                        frame, (self.frame_size[1], self.frame_size[0])
                    )
                except Exception as resize_err:
                    print(f"[ERROR] Error resizing frame from {self.url}: {resize_err}")
                    resized = np.zeros(self.frame_size, dtype=np.uint8)
            else:
                print(f"[WARN] Failed to get frame from {self.url}, using placeholder.")
                resized = np.zeros(self.frame_size, dtype=np.uint8)
            with self.lock:
                self.frame = resized
            # add a little wait to reduce the load of infinite loop
            time.sleep(0.01)

    def get_frame(self) -> np.ndarray:
        with self.lock:
            # return a copy of the frame
            return self.frame.copy()

    def stop(self) -> None:
        self.stopped = True
        # release the capture used in the thread
        if self.capture.isOpened():
            self.capture.release()


class Window:
    # DEFAULT_FRAME_SIZE は (height, width, channels)
    DEFAULT_FRAME_SIZE = (360, 640, 3)
    PORT_NO = 554

    def __init__(self, user_id: str, user_pw: str, layout: dict, cameras: dict) -> None:
        self._user_id = user_id
        self._user_pw = user_pw
        self._layout = layout
        self._cameras = cameras
        self.stream_threads: list[
            CameraStreamThread
        ] = []  # list of CameraStreamThread instances

    def show(self) -> None:
        print(f"Starting {APP_NAME}...")
        print("Press 'q' to quit.")

        # create a list of RTSP URLs for each camera (skip empty strings)
        self._urls = [
            f"rtsp://{self._user_id}:{self._user_pw}@{ip_address}:{self.PORT_NO}/stream2"
            for ip_address in self._cameras.values()
            if ip_address != ""
        ]

        # after creating the dedicated threads for each url, start them
        for url in self._urls:
            thread = CameraStreamThread(
                url,
                np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8),
                self.DEFAULT_FRAME_SIZE,
            )
            thread.start()
            self.stream_threads.append(thread)

        rows = self._layout["row"]
        cols = self._layout["col"]

        start_time = time.time()
        try:
            while True:
                try:
                    frames = self.get_frames()
                    combined_frame = self.create_grid(
                        frames=frames, rows=rows, cols=cols
                    )
                    cv2.imshow(APP_NAME, combined_frame)
                except Exception as e:
                    print(f"Error occurred while getting frames or creating grid: {e}")

                # check for exit key
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

                # reconnect all streams if 10 minutes have passed
                if time.time() - start_time > 600:
                    print("Reconnecting all streams...")
                    self.restart_all_streams()
                    start_time = time.time()

        finally:
            print("Stopping stream threads and releasing resources...")
            for thread in self.stream_threads:
                thread.stop()
            # for thread in self.stream_threads: # join raises segfault
            #    thread.join()
            cv2.destroyAllWindows()

    def get_frames(self) -> list:
        frames = []
        # fetch the latest frame from each thread
        for idx, stream_thread in enumerate(self.stream_threads):
            try:
                frame = stream_thread.get_frame()
                frames.append(frame)
            except Exception as e:
                print(f"[ERROR] Error getting frame from thread {idx}: {e}")
                frames.append(np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8))
        return frames

    def create_grid(self, frames: list, rows: int, cols: int) -> np.ndarray:
        # fill a placeholder image if no frames are available
        grid_frames = []
        for r in range(rows):
            # if no frames are available, fill with placeholder images
            row_frames = frames[r * cols : (r + 1) * cols]
            if len(row_frames) < cols:
                row_frames += [np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8)] * (
                    cols - len(row_frames)
                )
            row_concat = np.hstack(row_frames)
            grid_frames.append(row_concat)
        combined = np.vstack(grid_frames)
        return combined

    def restart_all_streams(self):
        # stop and restart all threads
        for thread in self.stream_threads:
            thread.stop()
            thread.join()
        self.stream_threads = []
        # create new threads for each url
        for url in self._urls:
            thread = CameraStreamThread(
                url,
                np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8),
                self.DEFAULT_FRAME_SIZE,
            )
            thread.start()
            self.stream_threads.append(thread)


class Camera:
    def __init__(self, init: bool = False) -> None:
        self.config_path = pathlib.Path(
            f"~/Library/Preferences/{APP_NAME}/config.ini"
        ).expanduser()
        self.config = configparser.ConfigParser()

        if not self.config_path.exists():
            print(f"Config file not found, creating one in {self.config_path}")
            self.create_config_file()

        if init:
            self.create_config_file()

        self.load_config()

    def create_config_file(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            row_num = self.input_positive_integer(
                prompt="Please enter the number of rows for cameras", default=2
            )
            col_num = self.input_positive_integer(
                prompt="Please enter the number of columns for cameras", default=3
            )
        except KeyboardInterrupt:
            Utility.exit_program()

        self._cameras = self.collect(row_num=row_num, col_num=col_num)

        self.config["LAYOUT"] = {"row": str(row_num), "col": str(col_num)}
        self.config["CAMERAS"] = self._cameras
        with open(self.config_path, "w") as f:
            self.config.write(f)

    def load_config(self) -> None:
        self.config.read(self.config_path)
        self._layout = {
            "row": self.config["LAYOUT"].getint("row"),
            "col": self.config["LAYOUT"].getint("col"),
        }
        self._cameras = dict(self.config["CAMERAS"])

    def collect(self, row_num: int = 0, col_num: int = 0) -> dict:
        cameras = {
            f"camera{row}-{col}": "" for row in range(row_num) for col in range(col_num)
        }

        print("Detecting cameras in the network...")
        found_cameras = self.find()
        if len(found_cameras) > 0:
            try:
                while True:
                    for key in cameras:
                        candidates = [
                            camera
                            for camera in found_cameras
                            if camera not in cameras.values()
                        ]
                        if len(candidates) == 0:
                            cameras[key] = ""
                        else:
                            cameras[key] = self.select(cameras=candidates)
                    if any(cameras.values()):
                        break
                    print("Please enter at least one IP address.")
            except KeyboardInterrupt:
                Utility.exit_program()
        else:
            try:
                while True:
                    for key in cameras:
                        cameras[key] = self.input_ip_address(
                            prompt=f"IP address or hostname for {key}",
                            default="192.168.1.2",
                        )
                    if any(cameras.values()):
                        break
                    print("Please enter at least one host IP address or hostname.")
            except KeyboardInterrupt:
                Utility.exit_program()

        return cameras

    def find(self) -> list:
        SEC_TO_WAIT = 1.07
        reachable_ip_addresses = self.get_arp_ip_address_list()
        if not reachable_ip_addresses:
            print("No reachable IP addresses found.")
            return []

        cnt_reachable_ip_addresses = len(reachable_ip_addresses)
        print(
            f"{cnt_reachable_ip_addresses} reachable IP addresses found.\nEstimated time to detect cameras: {cnt_reachable_ip_addresses * SEC_TO_WAIT:.2f} seconds."
        )
        found_cameras = [
            ip_address
            for ip_address in reachable_ip_addresses
            if self.scan_tcp_port(ip_address=ip_address)
        ]
        return found_cameras

    @staticmethod
    def get_arp_ip_address_list() -> list:
        try:
            output = subprocess.check_output(
                ["arp", "-a"], stderr=subprocess.STDOUT
            ).decode("utf-8")
        except subprocess.CalledProcessError as e:
            print("Failed to execute arp command.")
            print("Error Message:", e.output.decode("utf-8"))
            return []

        ip_address_list = re.findall(r"\((\d{1,3}(?:\.\d{1,3}){3})\)", output)
        return ip_address_list

    @staticmethod
    def scan_tcp_port(
        ip_address: str = "", port_num: int = 554, timeout: int = 2
    ) -> bool:
        print(f"Scanning {ip_address}:{port_num}...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip_address, port_num))
            sock.close()
            return result == 0
        except Exception:
            return False

    def select(self, cameras: list = []) -> str:
        RED = "\033[0;31m"
        RESET = "\033[0m"
        print("Select a camera from the list below:")
        for i, camera in enumerate(cameras, start=1):
            if i == 1:
                print(f"{RED}[{i}]: *  {camera}{RESET}")
            else:
                print(f"[{i}]:    {camera}")
        print("[0]:    Skip")
        while True:
            try:
                num = self.input_positive_integer(
                    prompt="Enter the number of the camera", default=1, accept_zero=True
                )
                if num == 0:
                    return ""
                if num > len(cameras):
                    print(f"Please enter a valid number. 1-{len(cameras)}.")
                    continue
                return cameras[num - 1]
            except KeyboardInterrupt:
                Utility.exit_program()

    @staticmethod
    def input_positive_integer(
        prompt: str = "", default: int = 1, accept_zero: bool = False
    ) -> int:
        while True:
            user_input = input(f"{prompt} [{default}]: ")
            if not user_input:
                return default
            try:
                num = int(user_input)
            except ValueError:
                print("Please enter a valid integer.")
                continue

            if accept_zero and num == 0:
                return num

            if num < 1:
                print("Please enter a valid integer.")
                continue

            return num

    def input_ip_address(self, prompt: str = "", default: str = "") -> str:
        def pre_input_hook() -> None:
            readline.insert_text(default)
            readline.redisplay()

        readline.set_pre_input_hook(pre_input_hook)
        while True:
            try:
                ip_address = input(f"{prompt} [{default}]: ")
                if not ip_address:
                    ip_address = default
                if self.is_valid_ip(ip_hostname=ip_address):
                    return ip_address
                else:
                    print("Please enter a valid IP address or hostname.")
            finally:
                readline.set_pre_input_hook()

    @staticmethod
    def is_valid_ip(ip_hostname: str = "") -> bool:
        if not ip_hostname:
            return False
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip_hostname):
            try:
                ipaddress.ip_address(ip_hostname.split(":")[0])
                return True
            except ValueError:
                return False
        else:
            try:
                ip_address = socket.gethostbyname(ip_hostname.split(":")[0])
                return bool(
                    re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip_address)
                )
            except socket.error:
                return False

    @property
    def cameras(self) -> dict:
        return self._cameras

    @property
    def layout(self) -> dict:
        return self._layout


class UserCredential:
    KEY_ID = "user_id"
    KEY_PW = "user_pw"

    def __init__(self, init: bool = False) -> None:
        self._user_id = ""
        self._user_pw = ""
        if not init:
            self._user_id = keyring.get_password(APP_NAME, self.KEY_ID) or ""
            self._user_pw = keyring.get_password(APP_NAME, self.KEY_PW) or ""
        self.ensure_credentials()

    def ensure_credentials(self) -> None:
        try:
            while not self._user_id or not self._user_pw:
                self._user_id = input("Please enter your Tapo ID, part before '@': ")
                self._user_pw = input("Please enter your Tapo Password: ")
                keyring.set_password(APP_NAME, self.KEY_ID, self._user_id)
                keyring.set_password(APP_NAME, self.KEY_PW, self._user_pw)
                self._user_id = keyring.get_password(APP_NAME, self.KEY_ID) or ""
                self._user_pw = keyring.get_password(APP_NAME, self.KEY_PW) or ""
        except KeyboardInterrupt:
            Utility.exit_program()

    @property
    def user_id(self) -> str:
        return self._user_id

    @user_id.setter
    def user_id(self, value: str = "") -> None:
        self._user_id = value
        keyring.set_password(APP_NAME, self.KEY_ID, value)

    @property
    def user_pw(self) -> str:
        return self._user_pw

    @user_pw.setter
    def user_pw(self, value: str = "") -> None:
        self._user_pw = value
        keyring.set_password(APP_NAME, self.KEY_PW, value)


class Utility:
    @staticmethod
    def exit_program() -> None:
        print("\n\nKeyboardInterrupt, exiting...")
        sys.exit(1)


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("This program is only supported on macOS.")

    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument(
        "-c",
        "--config",
        action="store_true",
        help="Create or edit the configuration file",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"{APP_NAME} {__version__}"
    )
    args = parser.parse_args()

    credentials = UserCredential(init=args.config)
    camera = Camera(init=args.config)
    window = Window(
        credentials.user_id, credentials.user_pw, camera.layout, camera.cameras
    )
    window.show()


if __name__ == "__main__":
    main()
