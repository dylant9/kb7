#!/usr/bin/env python3
"""
KB7 ISP-mode flash verifier  --  STRICTLY READ-ONLY.

Reads the SPI-NOR through the SoC's OWN flash controller while the device sits in
bootloader/ISP mode (10f5:5037), then verifies the SN_FWIN region CRCs.

WHY THIS MATTERS: our ESP32/flashrom reads test the *chip*. This tests the
*SoC reading the chip* -- the exact path the bootloader uses when it CRC-checks
regions at boot. If CRCs fail here but pass via the programmer, the SoC's flash
read path is the fault.

SAFETY: only these F6 subcodes are representable, and they are all non-mutating:
    0x00  identify
    0x01  read status
    0x05  NOR read
    0x17  enter 4-byte addressing (mode bit, not a write)
    0xF1  device descriptor
Program (0x06), erase (0x15/0x19), and every NAND opcode are absent by construction.
There is no code path in this file that can modify flash.

Requires libusb-1.0 and permission to claim the MSC interface (run with sudo, or
add a udev rule for 10f5:5037).

Usage:
    sudo python3 kb7-isp-verify.py                # verify CRCs (reads ~22MB)
    sudo python3 kb7-isp-verify.py -o dump.bin    # also save what it read
    sudo python3 kb7-isp-verify.py --full-chip -o full-32m.bin
"""

import argparse
import ctypes as ct
import struct
import sys
import zlib

VID, PID = 0x10F5, 0x5037
FLASH_BASE = 0x60000000
FLASH_SIZE = 0x02000000
BLOCK = 512
# 4 KiB per F6 05 command (8 blocks). This matches the Phase-0 test vector
# (F6 05 .. 00 08); larger chunks make the device's bulk-IN endpoint fail with
# LIBUSB_ERROR_IO, so its internal read buffer is evidently ~4 KiB.
CHUNK = 0x1000

# ---- the only subcodes this tool can emit (all read-only) --------------------
SUB_IDENTIFY, SUB_STATUS, SUB_READ, SUB_EN4B, SUB_DESC = 0x00, 0x01, 0x05, 0x17, 0xF1
_ALLOWED = {SUB_IDENTIFY, SUB_STATUS, SUB_READ, SUB_EN4B, SUB_DESC}
LOADER_IDENT = b"\x01\x01"
LOADER_DESCRIPTOR_LENGTH = 36
LOADER_DESCRIPTOR_MARKER = b"v0.001 test!"
LOADER_DESCRIPTOR_VERSION = LOADER_DESCRIPTOR_MARKER + bytes(4)
LOADER_DESCRIPTOR_DEVICE = b"SNC7320B" + bytes(4)
LOADER_DESCRIPTOR_MAGIC = struct.pack("<I", 0xBAABCFFC)

# ---- minimal libusb-1.0 ctypes binding --------------------------------------
# Load lazily so command builders and transport validators remain testable on
# offline hosts that do not have libusb installed.
lib = None


class _EP(ct.Structure):
    _fields_ = [("bLength", ct.c_uint8), ("bDescriptorType", ct.c_uint8),
                ("bEndpointAddress", ct.c_uint8), ("bmAttributes", ct.c_uint8),
                ("wMaxPacketSize", ct.c_uint16), ("bInterval", ct.c_uint8),
                ("bRefresh", ct.c_uint8), ("bSynchAddress", ct.c_uint8),
                ("extra", ct.POINTER(ct.c_ubyte)), ("extra_length", ct.c_int)]


class _IFD(ct.Structure):
    _fields_ = [("bLength", ct.c_uint8), ("bDescriptorType", ct.c_uint8),
                ("bInterfaceNumber", ct.c_uint8), ("bAlternateSetting", ct.c_uint8),
                ("bNumEndpoints", ct.c_uint8), ("bInterfaceClass", ct.c_uint8),
                ("bInterfaceSubClass", ct.c_uint8), ("bInterfaceProtocol", ct.c_uint8),
                ("iInterface", ct.c_uint8), ("endpoint", ct.POINTER(_EP)),
                ("extra", ct.POINTER(ct.c_ubyte)), ("extra_length", ct.c_int)]


class _IF(ct.Structure):
    _fields_ = [("altsetting", ct.POINTER(_IFD)), ("num_altsetting", ct.c_int)]


class _CFG(ct.Structure):
    _fields_ = [("bLength", ct.c_uint8), ("bDescriptorType", ct.c_uint8),
                ("wTotalLength", ct.c_uint16), ("bNumInterfaces", ct.c_uint8),
                ("bConfigurationValue", ct.c_uint8), ("iConfiguration", ct.c_uint8),
                ("bmAttributes", ct.c_uint8), ("MaxPower", ct.c_uint8),
                ("interface", ct.POINTER(_IF)),
                ("extra", ct.POINTER(ct.c_ubyte)), ("extra_length", ct.c_int)]


def _load_libusb():
    global lib
    if lib is not None:
        return lib

    api = ct.CDLL("libusb-1.0.so.0")
    api.libusb_open_device_with_vid_pid.restype = ct.c_void_p
    api.libusb_open_device_with_vid_pid.argtypes = [
        ct.c_void_p, ct.c_uint16, ct.c_uint16]
    api.libusb_get_device.restype = ct.c_void_p
    api.libusb_get_device.argtypes = [ct.c_void_p]
    api.libusb_get_active_config_descriptor.argtypes = [
        ct.c_void_p, ct.POINTER(ct.POINTER(_CFG))]
    api.libusb_bulk_transfer.argtypes = [
        ct.c_void_p, ct.c_ubyte, ct.POINTER(ct.c_ubyte),
        ct.c_int, ct.POINTER(ct.c_int), ct.c_uint]
    for fn in ("libusb_kernel_driver_active", "libusb_detach_kernel_driver",
               "libusb_attach_kernel_driver", "libusb_claim_interface",
               "libusb_release_interface"):
        getattr(api, fn).argtypes = [ct.c_void_p, ct.c_int]
    api.libusb_clear_halt.argtypes = [ct.c_void_p, ct.c_ubyte]
    api.libusb_close.argtypes = [ct.c_void_p]
    api.libusb_get_bus_number.argtypes = [ct.c_void_p]
    api.libusb_get_bus_number.restype = ct.c_uint8
    api.libusb_get_port_numbers.argtypes = [
        ct.c_void_p, ct.POINTER(ct.c_uint8), ct.c_int]
    api.libusb_get_port_numbers.restype = ct.c_int
    lib = api
    return api


def parse_csw(raw, expected_tag, expected_residue=0):
    """Validate a complete USB mass-storage CSW and fail closed.

    The KB7 loader has a proven F6-specific BOT quirk: it leaves residue equal
    to the CBW transfer length even after completing the exact data phase. A
    caller handling one of those commands must supply that exact expected
    value; this function never accepts an arbitrary nonzero residue.
    """
    if (not isinstance(expected_residue, int)
            or not 0 <= expected_residue <= 0xFFFFFFFF):
        raise ValueError("expected CSW residue must be a 32-bit unsigned integer")
    if len(raw) != 13:
        raise RuntimeError(f"short CSW: got {len(raw)}/13 bytes")
    sig, tag, residue, status = struct.unpack("<IIIB", raw)
    if sig != 0x53425355:
        raise RuntimeError(f"bad CSW signature 0x{sig:08x}")
    if tag != expected_tag:
        raise RuntimeError(f"CSW tag mismatch ({tag} != {expected_tag})")
    if residue != expected_residue:
        raise RuntimeError(
            f"unexpected CSW residue {residue} (expected {expected_residue})")
    if status != 0:
        raise RuntimeError(f"command failed with CSW status {status}")
    return status, residue


def stable_loader_descriptor(raw):
    """Validate F6 F1 and return only its initialized identity fields.

    V1.22 constructs bytes 0..27 and 32..35 explicitly, but its final 16-byte
    copy also includes four uninitialized stack bytes at 28..31. Those bytes
    must be transferred, but must not be treated as identity or state-binding
    material.
    """
    if len(raw) != LOADER_DESCRIPTOR_LENGTH:
        raise RuntimeError(
            f"unexpected F6 F1 descriptor length {len(raw)}; "
            f"expected {LOADER_DESCRIPTOR_LENGTH}")
    if raw[:16] != LOADER_DESCRIPTOR_VERSION:
        raise RuntimeError("unexpected F6 F1 loader version field")
    if raw[16:28] != LOADER_DESCRIPTOR_DEVICE:
        raise RuntimeError("unexpected F6 F1 loader device field")
    if raw[32:36] != LOADER_DESCRIPTOR_MAGIC:
        raise RuntimeError("unexpected F6 F1 loader descriptor magic")
    return raw[:28] + raw[32:36]


class Device:
    clear_halt_on_error = True

    def __init__(self):
        _load_libusb()
        self.ctx = ct.c_void_p()
        if lib.libusb_init(ct.byref(self.ctx)) != 0:
            raise RuntimeError("libusb_init failed")
        self.h = lib.libusb_open_device_with_vid_pid(self.ctx, VID, PID)
        if not self.h:
            raise RuntimeError(
                f"device {VID:04x}:{PID:04x} not found.\n"
                "  The keyboard must be in ISP/bootloader mode.\n"
                "  Check with: lsusb | grep 10f5")
        usb_device = lib.libusb_get_device(self.h)
        ports = (ct.c_uint8 * 8)()
        port_count = lib.libusb_get_port_numbers(usb_device, ports, len(ports))
        if port_count <= 0:
            raise RuntimeError("could not determine a stable USB topology path")
        port_path = ".".join(str(ports[i]) for i in range(port_count))
        self.device_path = f"{lib.libusb_get_bus_number(usb_device)}-{port_path}"
        self.iface, self.ep_in, self.ep_out, self.reattach = self._find_msc()
        if lib.libusb_kernel_driver_active(self.h, self.iface) == 1:
            lib.libusb_detach_kernel_driver(self.h, self.iface)
            self.reattach = True
        rc = lib.libusb_claim_interface(self.h, self.iface)
        if rc != 0:
            raise RuntimeError(f"claim_interface failed ({rc}) — try running with sudo")
        self.tag = 0

    def _find_msc(self):
        cfg = ct.POINTER(_CFG)()
        if lib.libusb_get_active_config_descriptor(
                lib.libusb_get_device(self.h), ct.byref(cfg)) != 0:
            raise RuntimeError("could not read config descriptor")
        for i in range(cfg.contents.bNumInterfaces):
            alt = cfg.contents.interface[i].altsetting[0]
            if alt.bInterfaceClass != 0x08:      # mass storage
                continue
            ein = eout = None
            for e in range(alt.bNumEndpoints):
                ep = alt.endpoint[e]
                if ep.bmAttributes & 0x03 != 0x02:   # bulk only
                    continue
                if ep.bEndpointAddress & 0x80:
                    ein = ep.bEndpointAddress
                else:
                    eout = ep.bEndpointAddress
            if ein is not None and eout is not None:
                return alt.bInterfaceNumber, ein, eout, False
        raise RuntimeError("no bulk mass-storage interface found")

    def _xfer(self, ep, buf, length, timeout=8000):
        n = ct.c_int(0)
        rc = lib.libusb_bulk_transfer(self.h, ct.c_ubyte(ep),
                                      ct.cast(buf, ct.POINTER(ct.c_ubyte)),
                                      length, ct.byref(n), timeout)
        if rc != 0:
            # The read-only reliability tool can opt to keep using the session
            # after a failed pass.  The destructive writer overrides this flag:
            # after a transport anomaly it must close without any recovery
            # traffic or another command in the uncertain BOT session.
            if self.clear_halt_on_error:
                lib.libusb_clear_halt(self.h, ct.c_ubyte(ep))
            raise RuntimeError(
                f"bulk transfer failed on ep 0x{ep:02x}: rc={rc}"
                f"{' (LIBUSB_ERROR_IO)' if rc == -1 else ''}, len={length}")
        return n.value

    def _xfer_exact(self, ep, buf, length, phase, timeout=8000):
        transferred = self._xfer(ep, buf, length, timeout)
        if transferred != length:
            raise RuntimeError(
                f"short {phase} transfer on ep 0x{ep:02x}: "
                f"got {transferred}/{length}")

    def cmd(self, cdb, data_len=0):
        """Raw Bulk-Only Transport. data-IN only (we never send data OUT)."""
        return self._command(cdb, data_len, _ALLOWED)

    def _command(self, cdb, data_len, allowed):
        if len(cdb) != 16 or cdb[0] != 0xF6:
            raise ValueError("CDB must be exactly 16 bytes and start with F6")
        if cdb[1] not in allowed:
            raise ValueError(f"subcode 0x{cdb[1]:02x} is not in the command whitelist")
        if data_len < 0:
            raise ValueError("data length cannot be negative")
        self.tag = (self.tag + 1) & 0xFFFFFFFF
        cbw = struct.pack("<IIIBBB", 0x43425355, self.tag, data_len,
                          0x80 if data_len else 0x00, 0, 16) + cdb
        self._xfer_exact(
            self.ep_out, ct.create_string_buffer(cbw, 31), 31, "CBW")
        out = b""
        if data_len:
            b = ct.create_string_buffer(data_len)
            self._xfer_exact(self.ep_in, b, data_len, "data-IN")
            out = bytes(b.raw[:data_len])
        csw = ct.create_string_buffer(13)
        self._xfer_exact(self.ep_in, csw, 13, "CSW")
        # V1.22 loader 0x5bac-0x5bb4 initializes residue from the CBW length;
        # its F6 wrapper returns zero at 0x6288, so 0x4f18-0x4f22 deducts no
        # bytes. Require that exact quirk, while all physical transfers above
        # remain exact-length and status/tag/signature remain strictly checked.
        status, residue = parse_csw(
            bytes(csw.raw[:13]), self.tag, expected_residue=data_len)
        return out, status, residue

    def close(self):
        try:
            lib.libusb_release_interface(self.h, self.iface)
            if self.reattach:
                lib.libusb_attach_kernel_driver(self.h, self.iface)
            lib.libusb_close(self.h)
        finally:
            lib.libusb_exit(self.ctx)


# ---- read-only command builders ---------------------------------------------
def cdb_simple(sub):
    return bytes([0xF6, sub]) + bytes(14)


def cdb_read(offset, nbytes):
    if nbytes % BLOCK or not (0 < nbytes <= 0xFFFF * BLOCK):
        raise ValueError("read length must be a positive multiple of 512")
    if offset < 0 or offset + nbytes > FLASH_SIZE:
        raise ValueError("read lies outside the 32-MiB flash")
    addr = FLASH_BASE + offset            # raw byte address (READ encoding)
    return (bytes([0xF6, SUB_READ, 0x00]) + struct.pack(">I", addr)
            + struct.pack(">H", nbytes // BLOCK) + bytes(7))


def fwin(d):
    return sum(zlib.crc32(d[o:o + 0x10000]) & 0xFFFFFFFF
               for o in range(0, len(d), 0x10000)) & 0xFFFFFFFF


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", help="also write what was read to this file")
    ap.add_argument("--full-chip", action="store_true",
                    help="read all 32 MiB (required when capturing a write-test baseline)")
    ap.add_argument("--chunk", type=lambda s: int(s, 0), default=CHUNK,
                    help=f"bytes per F6 05 command (default 0x{CHUNK:x}); "
                         "must be a multiple of 512. Lower it if you see "
                         "LIBUSB_ERROR_IO.")
    args = ap.parse_args()
    chunk = args.chunk
    if chunk % BLOCK or chunk <= 0:
        ap.error("--chunk must be a positive multiple of 512")

    dev = Device()
    try:
        print(f"connected: {VID:04x}:{PID:04x}  iface {dev.iface}  "
              f"ep_in 0x{dev.ep_in:02x} ep_out 0x{dev.ep_out:02x}")

        ident, st, residue = dev.cmd(
            cdb_simple(SUB_IDENTIFY), len(LOADER_IDENT))
        if ident != LOADER_IDENT:
            raise RuntimeError(
                f"unexpected F6 00 identity {ident.hex(' ')}; "
                f"expected {LOADER_IDENT.hex(' ')}")
        print(f"  F6 00 identify : {ident.hex(' ')}  "
              f"(status {st}, expected loader residue {residue})")
        desc, st, residue = dev.cmd(
            cdb_simple(SUB_DESC), LOADER_DESCRIPTOR_LENGTH)
        stable_loader_descriptor(desc)
        print(f"  F6 F1 descript.: {desc[:16].hex(' ')}...  "
              f"(status {st}, expected loader residue {residue})")

        _, st, _ = dev.cmd(cdb_simple(SUB_EN4B))
        print(f"  F6 17 enter 4-byte addressing: status {st}")

        print("\nreading header+manifest ...")
        head = b""
        while len(head) < 0x11000:
            d, st, _ = dev.cmd(cdb_read(len(head), chunk), chunk)
            if st != 0 or not d:
                raise RuntimeError(f"read failed at 0x{len(head):x} (status {st})")
            head += d
        if head[:8] != b"SNC7320A":
            print(f"  !! header magic is {head[:8]!r}, expected b'SNC7320A'")
        man = head[0x10000:0x11000]
        if man[:8] != b"SN_FWIN\x00":
            raise RuntimeError(f"manifest magic is {man[:8]!r} — aborting")
        print(f"  header OK, manifest OK (version {man[8:16].rstrip(bytes(1)).decode()})")

        regions = []
        for i, ent in ((0, 0x20), (1, 0x30), (2, 0x40)):
            load, store, length, crc = struct.unpack_from("<IIII", man, ent)
            regions.append((i, store - FLASH_BASE, length, crc))
        region_end = max(off + ln for _, off, ln, _ in regions)
        end = FLASH_SIZE if args.full_chip else region_end
        print(f"  need 0x{end:x} bytes ({end/1e6:.1f} MB) to cover all regions\n")

        data = bytearray(head)
        while len(data) < end:
            n = min(chunk, end - len(data))
            n = ((n + BLOCK - 1) // BLOCK) * BLOCK
            d, st, _ = dev.cmd(cdb_read(len(data), n), n)
            if st != 0 or len(d) != n:
                raise RuntimeError(f"read failed at 0x{len(data):x} "
                                   f"(status {st}, got {len(d)}/{n})")
            data += d
            pct = 100.0 * len(data) / end
            print(f"\r  reading via SoC: {pct:5.1f}%  ({len(data):,}/{end:,})",
                  end="", flush=True)
        print("\n")

        allpass = True
        for i, off, length, crc in regions:
            calc = fwin(bytes(data[off:off + length]))
            ok = calc == crc
            allpass &= ok
            print(f"  region{i}: declared=0x{crc:08x} computed=0x{calc:08x} "
                  f"{'PASS' if ok else '*** FAIL ***'}")

        print()
        if allpass:
            print("ALL REGION CRCs PASS as read through the SoC's own flash controller.")
            print("=> The bootloader's integrity check is NOT the reason it drops to ISP.")
        else:
            print("A REGION FAILS when read through the SoC's own flash controller,")
            print("even though the programmer reads the chip cleanly.")
            print("=> The SoC's flash read path is the fault, not the chip contents.")

        if args.out:
            with open(args.out, "xb") as f:
                f.write(bytes(data))
            print(f"\nsaved {len(data):,} bytes to {args.out}")
    finally:
        dev.close()


if __name__ == "__main__":
    sys.exit(main())
