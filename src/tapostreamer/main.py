import argparse
import configparser
import ipaddress
import pathlib
import re
import readline
import socket
import subprocess
import sys
from importlib.metadata import version


import cv2
import keyring
import numpy as np


# Application Name
APP_NAME = "TapoStreamer"
__version__ = version("tapostreamer")


class Window:
    DEFAULT_FRAME_SIZE = (360, 640, 3)
    PORT_NO = 554

    def __init__(self, user_id: str, user_pw: str, layout: dict, cameras: dict) -> None:
        self._user_id = user_id
        self._user_pw = user_pw
        self._layout = layout
        self._cameras = cameras

    def show(self) -> None:
        print(f"Starting {APP_NAME}...")
        print("Press 'q' to quit.")
        urls = [
            f"rtsp://{self._user_id}:{self._user_pw}@{ip_address}:{self.PORT_NO}/stream2"
            for ip_address in self._cameras.values()
            if ip_address != ""
        ]
        caps = [cv2.VideoCapture(url) for url in urls]

        rows = self._layout["row"]
        cols = self._layout["col"]

        try:
            while True:
                frames = self.get_frames(caps)
                combined_frame = self.create_grid(frames=frames, rows=rows, cols=cols)
                cv2.imshow(APP_NAME, combined_frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            for cap in caps:
                cap.release()
            cv2.destroyAllWindows()

    def get_frames(self, caps: list = []) -> list:
        frames = []
        for cap in caps:
            ret, frame = cap.read()
            if ret:
                # フレームを統一したサイズにリサイズ
                frame = cv2.resize(
                    frame, (self.DEFAULT_FRAME_SIZE[1], self.DEFAULT_FRAME_SIZE[0])
                )
                frames.append(frame)
            else:
                frames.append(np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8))
        return frames

    def create_grid(
        self, frames: list = [], rows: int = 0, cols: int = 0
    ) -> np.ndarray:
        grid_frames = [
            np.hstack(
                frames[r * cols : (r + 1) * cols]
                + [np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8)]
                * (cols - len(frames[r * cols : (r + 1) * cols]))
            )
            for r in range(rows)
        ]
        return np.vstack(grid_frames)


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
