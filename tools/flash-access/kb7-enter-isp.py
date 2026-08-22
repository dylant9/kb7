#!/usr/bin/env python3
"""
Put the KB7 into bootloader/ISP mode (10f5:5037) from normal operation.

Sends the vendor mode-switch HID feature report to the ff90:ff00 vendor
interface. This is the documented vendor path -- it is a VOLATILE mode change,
not a firmware write, and a power-cycle returns the keyboard to normal.

Only needed if you want to force ISP mode. If the keyboard has already dropped
to ISP on its own, skip this and run kb7-isp-verify.py directly.

Usage:  sudo python3 kb7-enter-isp.py
"""

import fcntl
import glob
import os
import sys

VID = "10F5"
# HIDIOCSFEATURE(len) = _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, len)
def HIDIOCSFEATURE(size):
    return (3 << 30) | (ord('H') << 8) | 0x06 | (size << 16)

# 65 bytes: report id 0x00, then the vendor magic, then zero padding.
REPORT = bytes([0x00, 0xAA, 0x55, 0xA5, 0x5A, 0xFF, 0x00, 0x33, 0xCC]) + bytes(56)
VENDOR_USAGE_PAGE = bytes([0x06, 0x90, 0xFF])      # Usage Page (0xFF90)


def candidates():
    found = []
    for hr in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        name = os.path.basename(hr)
        try:
            uevent = open(f"{hr}/device/uevent").read()
        except OSError:
            continue
        if VID not in uevent.upper():
            continue
        try:
            rd = open(f"{hr}/device/report_descriptor", "rb").read()
        except OSError:
            rd = b""
        found.append((name, VENDOR_USAGE_PAGE in rd, uevent))
    return found


def main():
    cands = candidates()
    if not cands:
        print("No Turtle Beach (10f5) hidraw device found.")
        print("Is the keyboard connected and booted normally?")
        print("Check:  lsusb | grep 10f5")
        return 1

    print("Turtle Beach HID interfaces:")
    for name, is_vendor, _ in cands:
        print(f"  /dev/{name}   vendor-usage-page(0xFF90): {is_vendor}")

    targets = [n for n, v, _ in cands if v]
    if not targets:
        print("\nNo interface exposes usage page 0xFF90 — cannot identify the")
        print("vendor interface safely. Aborting rather than guessing.")
        return 1
    target = f"/dev/{targets[0]}"

    print(f"\nAbout to send the vendor mode-switch feature report to {target}.")
    print("Effect: the keyboard re-enumerates as 10f5:5037 (bootloader/ISP mode).")
    print("This is volatile — a power-cycle restores normal operation.")
    if input("Proceed? [y/N] ").strip().lower() != "y":
        print("aborted.")
        return 1

    try:
        fd = os.open(target, os.O_RDWR)
    except PermissionError:
        print(f"permission denied opening {target} — run with sudo")
        return 1
    try:
        fcntl.ioctl(fd, HIDIOCSFEATURE(len(REPORT)), bytearray(REPORT))
        print("sent. Give it a second, then check:  lsusb | grep 10f5")
        print("Expect:  10f5:5037 Turtle Beach USB2.0 Mass Storage")
    except OSError as e:
        # The device often drops off the bus mid-ioctl as it re-enumerates.
        print(f"ioctl returned {e} — this is common if the device re-enumerated")
        print("immediately. Check:  lsusb | grep 10f5")
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
