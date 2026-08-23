CROSS ?= arm-none-eabi-
CC := $(CROSS)gcc
OBJDUMP := $(CROSS)objdump
READELF := $(CROSS)readelf
SIZE := $(CROSS)size
NM := $(CROSS)nm

CFLAGS := -mcpu=cortex-m3 -mthumb -mfloat-abi=soft -std=gnu11 -Os -g3 \
	-ffreestanding -fno-builtin -fno-common -fno-stack-protector \
	-fdata-sections -ffunction-sections -fno-unwind-tables \
	-fno-asynchronous-unwind-tables -Wall -Wextra -Werror -MMD -MP -Iinclude \
	$(PROFILE_DEFINES) $(EXTRA_CFLAGS)
LDFLAGS := -nostdlib -Wl,--build-id=none,--gc-sections

COMMON := common/memory.c common/crc32.c
CORE0_SRC := core0/startup.c core0/main.c core0/usb.c $(COMMON) \
	drivers/gpio.c drivers/timer.c drivers/clock.c drivers/dram.c drivers/flash.c drivers/recovery.c
CORE1_SRC := core1/startup.c core1/main.c core1/storage.c core1/profile_blob.c \
	core1/host_server.c core1/usb_client.c $(COMMON) \
	common/host_protocol.c drivers/gpio.c drivers/timer.c drivers/lcd.c drivers/touch.c \
	drivers/rgb.c drivers/mcu2.c drivers/hall_policy.c drivers/encoder.c \
	drivers/keymap.c drivers/input_pipeline.c drivers/input_profiles.c \
	drivers/action_bar.c drivers/lighting.c ui/screen_parser.c ui/renderer.c
CORE0_OBJ := $(patsubst %.c,build/core0/%.o,$(CORE0_SRC))
CORE1_OBJ := $(patsubst %.c,build/core1/%.o,$(CORE1_SRC))
DEPS := $(CORE0_OBJ:.o=.d) $(CORE1_OBJ:.o=.d)

.PHONY: all clean verify audit-profile integration-check bundle
all: build/core0.elf build/core1.elf verify

build/core0/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/core1/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/core0.elf: $(CORE0_OBJ) linker/core0.ld
	$(CC) $(CFLAGS) $(LDFLAGS) -T linker/core0.ld -Wl,-Map=build/core0.map \
		$(CORE0_OBJ) -lgcc -o $@
	$(OBJDUMP) -d -S $@ > build/core0.dis

build/core1.elf: $(CORE1_OBJ) linker/core1.ld
	$(CC) $(CFLAGS) $(LDFLAGS) -T linker/core1.ld -Wl,-Map=build/core1.map \
		$(CORE1_OBJ) -lgcc -o $@
	$(OBJDUMP) -d -S $@ > build/core1.dis

verify: build/core0.elf build/core1.elf
	@set -eu; \
	for image in core0 core1; do \
		$(READELF) -r build/$$image.elf | grep -q 'There are no relocations'; \
		$(SIZE) build/$$image.elf; \
	done; \
	test "$$($(NM) -S build/core0.elf | awk '$$4 == "vectors" { print $$2 }')" = 0000013c

audit-profile:
	$(MAKE) clean
	$(MAKE) all PROFILE_DEFINES='-DKB7_ENABLE_UNVERIFIED_DRAM_INIT=1 \
		-DKB7_ENABLE_UNVERIFIED_RECOVERY_CHORD=1 \
		-DKB7_ENABLE_DISPLAY=1 -DKB7_ENABLE_TOUCH=1 -DKB7_ENABLE_RGB=1 \
		-DKB7_ENABLE_MCU2=1 -DKB7_ENABLE_ENCODER=1 \
		-DKB7_ENABLE_ACTION_BAR=1'

# Compiles every hardware-facing branch so CI catches rot. These defines are
# compile-time assertions only; this target is not evidence that a board has
# passed the physical validation gates named by the macros. The nonzero USB
# identity is a compile-test sentinel and must never be shipped or deployed.
integration-check:
	$(MAKE) clean
	$(MAKE) all PROFILE_DEFINES='-DKB7_ENABLE_UNVERIFIED_DRAM_INIT=1 \
		-DKB7_ENABLE_UNVERIFIED_RECOVERY_CHORD=1 \
		-DKB7_ENABLE_DISPLAY=1 -DKB7_ENABLE_TOUCH=1 -DKB7_ENABLE_RGB=1 \
		-DKB7_ENABLE_MCU2=1 -DKB7_MCU2_BOARD_PROFILE_VERIFIED=1 \
		-DKB7_ENABLE_ENCODER=1 -DKB7_USB_BOARD_PROFILE_VERIFIED=1 \
		-DKB7_USB_VENDOR_ID=0xcafe -DKB7_USB_PRODUCT_ID=0x4001 \
		-DKB7_ENABLE_ACTION_BAR=1 -DKB7_ACTION_BAR_BOARD_PROFILE_VERIFIED=1 \
		-DKB7_ENABLE_FLASH_MUTATION=1'
	@set -eu; \
	usb_size=`$(NM) -S build/core0.elf | awk '$$4 == "kb7_usb_init" { print $$2 }'`; \
	test -n "$$usb_size"; \
	test $$((0x$$usb_size)) -gt 128

bundle:
	@echo "Installable-bundle generation is intentionally unavailable through this Makefile." >&2
	@echo "The separate offline planner is non-executing and remains flash_approved=false." >&2
	@echo "See ../docs/USB-UPDATER-OFFLINE-DESIGN-2026-08-23.md." >&2
	@exit 2

clean:
	rm -rf build

-include $(DEPS)
