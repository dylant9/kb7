#!/bin/bash
# KB7 flash read @ 16 MHz  -- READ ONLY, never writes.
# Purpose: test whether the flash reads reliably at high SPI clock.
#
# PRECONDITIONS:
#   1. RST switch CLOSED (SoC held in reset)  -- verify: lsusb | grep 10f5 shows NO 5037/5038
#   2. Keyboard USB plugged in (powers the flash chip)
#   3. ESP32 connected, /dev/ttyACM0 present
#   4. Do NOT connect ESP32 3.3V to flash pin 8 while the board is powered
#
# Usage: ./kb7-read-16m.sh <output-path> [expected-sha256]

set -u
SPEED=16M
DEV="${KB7_SERPROG_DEV:-/dev/ttyACM0}"
CHIP="MX25L25635F/MX25L25645G"
OUT="${1:?usage: kb7-read-16m.sh <output-path> [expected-sha256]}"
EXPECTED="${2:-}"
if [ -n "$EXPECTED" ] && [[ ! "$EXPECTED" =~ ^[0-9A-Fa-f]{64}$ ]]; then
  echo "ERROR: expected SHA-256 must be exactly 64 hexadecimal characters."
  exit 2
fi
EXPECTED="${EXPECTED,,}"

echo "=== KB7 flash read @ ${SPEED} (read-only) ==="
[ -e "$DEV" ] || { echo "ERROR: $DEV not found — is the ESP32 plugged in?"; exit 1; }

if lsusb | grep '10f5:' | grep -qv '10f5:503d'; then
  echo "WARNING: SoC is enumerated (5037/5038) — RST is NOT holding it in reset."
  echo "         The SoC will contend with the programmer on the SPI bus."
  echo "         Close the RST switch and re-run. Continuing anyway in 5s (Ctrl-C to abort)..."
  sleep 5
fi

echo "reading 32MB at ${SPEED} ..."
time flashrom -p "serprog:dev=${DEV}:921600,spispeed=${SPEED}" -c "$CHIP" -r "$OUT" --progress
rc=$?
echo
if [ $rc -ne 0 ]; then
  echo "RESULT: flashrom exited $rc — read FAILED at ${SPEED}."
  echo "        (A hard failure at this speed is itself a useful data point.)"
  exit $rc
fi

GOT=$(sha256sum "$OUT" | cut -d' ' -f1)
echo "sha256   : $GOT"
if [ -z "$EXPECTED" ]; then
  echo "RESULT: read complete; no reference SHA-256 was supplied."
elif [ "$GOT" = "$EXPECTED" ]; then
  echo "RESULT: MATCH — flash read cleanly at ${SPEED}."
else
  echo "expected : $EXPECTED"
  echo "RESULT: *** REFERENCE MISMATCH at ${SPEED} ***"
  echo "        Preserve both reads and use kb7-compare.sh to locate differences."
fi
