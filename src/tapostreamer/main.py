#!/usr/bin/env python3
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
import logging
from importlib.metadata import version
import cv2
import keyring
import numpy as np
import multiprocessing
from multiprocessing import Process, Event, Queue

logging.basicConfig(level=logging.WARNING)

APP_NAME = "TapoStreamer"
__version__ = version("tapostreamer")


def camera_stream_worker(url: str, frame_size: tuple, out_queue, stop_event):
    """
    Fetch frames from a camera using VideoCapture at ~15 fps.
    """
    capture = cv2.VideoCapture(url)
    desired_interval = 0.07  # Target 15 frames per second (~0.0667 sec per frame)
    failure_count = 0
    max_failures = 30  # e.g., after 30 consecutive failures, try reconnect
    while not stop_event.is_set():
        loop_start = time.perf_counter()
        if not capture.isOpened():
            logging.warning(f"Process for {url} finds capture closed. Reconnecting...")
            capture.release()
            capture = cv2.VideoCapture(url)

        try:
            ret, frame = capture.read()
        except Exception as e:
            logging.error(f"Exception in process reading {url}: {e}")
            ret = False

        if ret and frame is not None:
            try:
                resized = cv2.resize(frame, (frame_size[1], frame_size[0]))
                failure_count = 0
            except Exception as resize_err:
                logging.error(f"Error resizing frame from {url}: {resize_err}")
                resized = np.zeros(frame_size, dtype=np.uint8)
                failure_count += 1
        else:
            logging.warning(f"Failed to get frame from {url}, using placeholder.")
            resized = np.zeros(frame_size, dtype=np.uint8)
            failure_count += 1

        # Always keep only the latest frame in the queue
        # while not out_queue.empty():
        #    try:
        #        out_queue.get_nowait()
        #    except Exception:
        #        break
        try:
            out_queue.put(resized, block=True, timeout=0.03)
        except Exception:
            pass
            # logging.error(f"Cannot put frame into queue for {url}: {e}")

        if failure_count > max_failures:
            logging.error(f"Maximum failure count reached for {url}")
            capture.release()
            time.sleep(1)
            capture = cv2.VideoCapture(url)
            failure_count = 0

        # Calculate elapsed processing time and sleep only if needed.
        elapsed = time.perf_counter() - loop_start
        remaining_time = desired_interval - elapsed
        if remaining_time > 0:
            time.sleep(remaining_time)
    capture.release()


class CameraStreamProcess:
    def __init__(self, url: str, default_frame: np.ndarray, frame_size: tuple):
        self.url = url
        self.frame_size = frame_size  # (height, width, channels)
        self.default_frame = default_frame.copy()  # placeholder
        self.queue = Queue(maxsize=5)
        self.stop_event = Event()
        self.process = Process(
            target=camera_stream_worker,
            args=(self.url, self.frame_size, self.queue, self.stop_event),
            daemon=True,
        )

    def start(self) -> None:
        self.process.start()

    def get_frame(self) -> np.ndarray:
        try:
            frame = self.queue.get_nowait()
            return frame
        except Exception:
            return self.default_frame.copy()

    def stop(self) -> None:
        self.stop_event.set()
        if self.process.is_alive():
            self.process.join(timeout=1)


class Window:
    # DEFAULT_FRAME_SIZE (height, width, channels)
    DEFAULT_FRAME_SIZE = (360, 640, 3)
    PORT_NO = 554

    def __init__(self, user_id: str, user_pw: str, layout: dict, cameras: dict) -> None:
        self._user_id = user_id
        self._user_pw = user_pw
        self._layout = layout
        self._cameras = cameras
        self.stream_processes: list[CameraStreamProcess] = []

    def show(self) -> None:
        logging.info(f"Starting {APP_NAME}...")
        print("Press 'q' to quit.")

        # create rtsp urls for each camera
        self._urls = [
            f"rtsp://{self._user_id}:{self._user_pw}@{ip_address}:{self.PORT_NO}/stream2"
            for ip_address in self._cameras.values()
            if ip_address != ""
        ]

        # Create processes for each URL
        for url in self._urls:
            proc = CameraStreamProcess(
                url,
                np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8),
                self.DEFAULT_FRAME_SIZE,
            )
            proc.start()
            self.stream_processes.append(proc)

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
                    time.sleep(0.07)
                except Exception as e:
                    logging.error(
                        f"Error occurred while getting frames or creating grid: {e}"
                    )

                # check for exit key
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

                # reconnect all streams if 10 minutes have passed
                if time.time() - start_time > 600:
                    # print("Reconnecting all streams...")
                    # self.restart_all_streames()
                    start_time = time.time()

        finally:
            print("Stopping stream processes and releasing resources...")
            for proc in self.stream_processes:
                proc.stop()
            logging.debug("Stopped stream processes and releasing resources...")
            cv2.destroyAllWindows()

    def get_frames(self) -> list:
        frames = []
        for idx, proc in enumerate(self.stream_processes):
            try:
                frame = proc.get_frame()
                frames.append(frame)
            except Exception as e:
                logging.error(f"Error getting frame from process {idx}: {e}")
                frames.append(np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8))
        return frames

    def create_grid(self, frames: list, rows: int, cols: int) -> np.ndarray:
        grid_frames = []
        for r in range(rows):
            row_frames = frames[r * cols : (r + 1) * cols]
            if len(row_frames) < cols:
                row_frames += [np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8)] * (
                    cols - len(row_frames)
                )
            row_concat = np.hstack(row_frames)
            grid_frames.append(row_concat)
        combined = np.vstack(grid_frames)
        return combined

    def restart_all_streames(self):
        logging.debug("Stopping existing processes...")
        for proc in self.stream_processes:
            proc.stop()
        self.stream_processes = []
        logging.debug("Creating new processes...")
        for url in self._urls:
            proc = CameraStreamProcess(
                url,
                np.zeros(self.DEFAULT_FRAME_SIZE, dtype=np.uint8),
                self.DEFAULT_FRAME_SIZE,
            )
            proc.start()
            self.stream_processes.append(proc)


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

    multiprocessing.set_start_method("spawn", force=True)

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
