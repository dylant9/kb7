CROSS ?= arm-none-eabi-
CC := $(CROSS)gcc
OBJDUMP := $(CROSS)objdump
READELF := $(CROSS)readelf
SIZE := $(CROSS)size

CFLAGS := -mcpu=cortex-m4 -mthumb -mfloat-abi=soft -std=gnu11 -Os -g3 \
	-ffreestanding -fno-builtin -fno-common -fno-stack-protector \
	-fdata-sections -ffunction-sections -fno-unwind-tables \
	-fno-asynchronous-unwind-tables -Wall -Wextra -Werror -MMD -MP -Iinclude
LDFLAGS := -nostdlib -Wl,--build-id=none,--gc-sections

COMMON := common/memory.c common/crc32.c
CORE0_SRC := core0/startup.c core0/main.c core0/usb.c $(COMMON) \
	drivers/gpio.c drivers/timer.c drivers/clock.c drivers/dram.c drivers/flash.c drivers/recovery.c
CORE1_SRC := core1/startup.c core1/main.c core1/storage.c core1/host_server.c core1/usb_client.c $(COMMON) \
	common/host_protocol.c drivers/gpio.c drivers/timer.c drivers/lcd.c drivers/touch.c \
	drivers/rgb.c drivers/mcu2.c drivers/hall_policy.c drivers/encoder.c \
	ui/screen_parser.c ui/renderer.c
CORE0_OBJ := $(patsubst %.c,build/core0/%.o,$(CORE0_SRC))
CORE1_OBJ := $(patsubst %.c,build/core1/%.o,$(CORE1_SRC))
DEPS := $(CORE0_OBJ:.o=.d) $(CORE1_OBJ:.o=.d)

.PHONY: all clean verify bundle
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
	done

bundle:
	@echo "Flash-image generation is intentionally unavailable in the public source tree." >&2
	@echo "See ../docs/SECURITY-AUDIT-2026-08-17.md." >&2
	@exit 2

clean:
	rm -rf build

-include $(DEPS)
