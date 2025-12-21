# TapoStreamer

![License](https://img.shields.io/badge/license-MIT-blue.svg)

## Overview

TapoStreamer is an Python application that shows the video streaming from the cameras made by TP-Link.
It runs on macOS.

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [License](#license)

## Installation

Just add tap and install homebrew package.

```bash
brew tap rioriost/tapostreamer
brew install tapostreamer
```

## Usage

Execute tapostreamer command.

```bash
tapostreamer
```

The first time, tapostreamer prompts you to input a username and password for the camera. The username and password are stored in the keychain.

```bash
Please enter your Tapo ID, part before '@': your_account
Please enter your Tapo Password: xxxxxxxxxxxxxxxx
```

Then, tapostreamer prompts you to input the number of rows and columns for the cameras. The default values are 2 and 3, respectively.

```bash
Config file not found, creating one in /Users/rifujita/Library/Preferences/TapoStreamer/config.ini
Please enter the number of rows for cameras [2]:
Please enter the number of columns for cameras [3]:
```

After that, tapostreamer detects the cameras in the network and shows the list of the cameras. You can select the cameras to show the video streaming.

```bash
Detecting cameras in the network...
16 reachable IP addresses found.
Estimated time to detect cameras: 17.12 seconds.
Select a camera from the list below:
[1]: *  192.168.50.6
[2]:    192.168.50.7
[3]:    192.168.50.8
[4]:    192.168.50.10
[5]:    192.168.50.128
[0]:    Skip
Enter the number of the camera [1]:
Select a camera from the list below:
[1]: *  192.168.50.7
[2]:    192.168.50.8
[3]:    192.168.50.10
[4]:    192.168.50.128
[0]:    Skip
Enter the number of the camera [1]:
Select a camera from the list below:
[1]: *  192.168.50.8
[2]:    192.168.50.10
[3]:    192.168.50.128
[0]:    Skip
Enter the number of the camera [1]:
Select a camera from the list below:
[1]: *  192.168.50.10
[2]:    192.168.50.128
[0]:    Skip
Enter the number of the camera [1]:
Select a camera from the list below:
[1]: *  192.168.50.128
[0]:    Skip
Enter the number of the camera [1]:
```

Finally, tapostreamer shows the video streaming from the selected cameras.

```bash
Starting TapoStreamer...
Press 'q' to quit.
```

## Release Notes

### 0.3.7 Release
* Dependency Update

### 0.3.6 Release
* Security Update

### 0.3.5 Release
* Dependency Update

### 0.3.4 Release
* Dependency Update

### 0.3.3 Release
* Dependency Update

### 0.2.0 Release
* Multi-threading support.

### 0.1.2 Release
* Small bug fixes.

### 0.1.1 Release
* Small bug fixes.

### 0.1.0 Release
* First release.

## Known Issues

### 0.2.0 Release
* tapostreamer sometimes fails with 'segmentation fault' when it's terminated. Due to the OpenCV implementation.

## License
MIT License
