CROSS ?= arm-none-eabi-
CC := $(CROSS)gcc
OBJDUMP := $(CROSS)objdump
OBJCOPY := $(CROSS)objcopy
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
CORE0_ASM := drivers/recovery_trampoline.S
CORE1_SRC := core1/startup.c core1/main.c core1/storage.c core1/profile_blob.c \
	core1/host_server.c core1/usb_client.c $(COMMON) \
	common/host_protocol.c drivers/gpio.c drivers/timer.c drivers/lcd.c drivers/touch.c \
	drivers/rgb.c drivers/mcu2.c drivers/hall_policy.c drivers/encoder.c \
	drivers/keymap.c drivers/input_pipeline.c drivers/input_profiles.c \
	drivers/action_bar.c drivers/lighting.c ui/screen_parser.c ui/renderer.c
# Region-1 loader-reentry proof: stock region 0 stays installed and calls
# this image at the fixed stock entry; see linker/region1-reentry-proof.ld.
REGION1_PROOF_SRC := core1/region1_reentry_proof.c drivers/recovery.c
REGION1_PROOF_ASM := drivers/recovery_trampoline.S
CORE0_OBJ := $(patsubst %.c,build/core0/%.o,$(CORE0_SRC))
CORE0_OBJ += $(patsubst %.S,build/core0/%.o,$(CORE0_ASM))
CORE1_OBJ := $(patsubst %.c,build/core1/%.o,$(CORE1_SRC))
REGION1_PROOF_OBJ := $(patsubst %.c,build/region1-proof/%.o,$(REGION1_PROOF_SRC))
REGION1_PROOF_OBJ += $(patsubst %.S,build/region1-proof/%.o,$(REGION1_PROOF_ASM))
DEPS := $(CORE0_OBJ:.o=.d) $(CORE1_OBJ:.o=.d) $(REGION1_PROOF_OBJ:.o=.d)

.PHONY: all clean verify audit-profile integration-check recovery-proof \
	region1-reentry-proof bundle
all: build/core0.elf build/core1.elf verify

build/core0/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/core1/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/core0/%.o: %.S
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/region1-proof/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/region1-proof/%.o: %.S
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/region1-reentry-proof.elf: $(REGION1_PROOF_OBJ) linker/region1-reentry-proof.ld
	$(CC) $(CFLAGS) $(LDFLAGS) -T linker/region1-reentry-proof.ld \
		-Wl,-Map=build/region1-reentry-proof.map $(REGION1_PROOF_OBJ) -lgcc -o $@
	$(OBJDUMP) -d -S $@ > build/region1-reentry-proof.dis

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
		-DKB7_ENABLE_UNVERIFIED_LOADER_REENTRY=1 \
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
		-DKB7_ENABLE_UNVERIFIED_LOADER_REENTRY=1 \
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

# Builds a planner-compatible ELF whose Core-0 reset path immediately invokes
# the stock-equivalent loader relocation. The offline planner must still apply
# the pair/checksum fixups. This target emits no bundle and touches no device.
recovery-proof:
	$(MAKE) clean
	$(MAKE) all PROFILE_DEFINES='-DKB7_ENABLE_UNVERIFIED_LOADER_REENTRY=1 \
		-DKB7_BUILD_LOADER_REENTRY_PROOF=1'
	@set -eu; \
		blob=`$(READELF) -sW build/core0.elf | awk '$$8 == "kb7_loader_trampoline_blob_start" { print $$2 }'`; \
		size=`$(READELF) -sW build/core0.elf | awk '$$8 == "kb7_loader_trampoline_blob_start" { print $$3 }'`; \
		end=`$(READELF) -sW build/core0.elf | awk '$$8 == "kb7_loader_trampoline_blob_end" { print $$2 }'`; \
		entry=`$(READELF) -sW build/core0.elf | awk '$$8 == "kb7_loader_trampoline_start" { print $$2 }'`; \
		test -n "$$blob"; \
		test -n "$$size"; \
		test $$((0x$$blob & 1)) -eq 0; \
		test $$((0x$$end)) -eq $$((0x$$blob + $$size)); \
		test $$((0x$$entry)) -eq $$((0x$$blob + 1)); \
		test $$size -gt 0; \
		test $$size -le 192; \
		$(READELF) -rW build/core0/drivers/recovery.o | \
			grep -q 'kb7_loader_trampoline_blob_start'; \
		$(READELF) -rW build/core0/drivers/recovery.o | \
			grep -q 'kb7_loader_trampoline_blob_end'; \
		$(READELF) -rW build/core0/drivers/recovery.o | \
			grep -q 'kb7_loader_trampoline_relocate_and_enter'; \
		! $(READELF) -rW build/core0/drivers/recovery_trampoline.o | \
			grep -Eq "Relocation section '.rel.text.kb7_loader_(relocator|trampoline)'"; \
		$(OBJCOPY) --dump-section \
			.text.kb7_loader_relocator=build/loader-reentry-relocator.bin \
			build/core0/drivers/recovery_trampoline.o; \
		test "`wc -c < build/loader-reentry-relocator.bin`" -eq 84; \
		test "`sha256sum build/loader-reentry-relocator.bin | awk '{ print $$1 }'`" = \
			a8c82aa423cc089a563fed7bf2f319f39b2945addf065b47849c04c4d7c793eb; \
		$(OBJCOPY) --dump-section \
			.text.kb7_loader_trampoline=build/loader-reentry-trampoline.bin \
			build/core0/drivers/recovery_trampoline.o; \
		test "`wc -c < build/loader-reentry-trampoline.bin`" -eq 72; \
		test "`sha256sum build/loader-reentry-trampoline.bin | awk '{ print $$1 }'`" = \
			43bde11ee9089c930b8e67c6b7d569aec736d719f59f24c6b207d80309a2f539; \
		$(OBJCOPY) -O binary build/core0.elf build/loader-reentry-proof-core0.bin; \
		test "`wc -c < build/loader-reentry-proof-core0.bin`" -eq 1260; \
		test "`sha256sum build/loader-reentry-proof-core0.bin | awk '{ print $$1 }'`" = \
			b0b3b75ab06bd00b152f86446de623b9029ff3ab9d164f6f4387243d2556b272; \
		$(OBJDUMP) -d build/core0.elf | grep -q '60001000'; \
		$(OBJDUMP) -d build/core0.elf | grep -q 'e000ed0c'; \
		$(OBJDUMP) -d build/core0.elf | grep -q '05fa0004'; \
		$(OBJDUMP) -d build/core0.elf | \
			sed -n '/<kb7_loader_trampoline_relocate_and_enter>:/,/^$$/p' | \
			grep -q 'mrs.*MSP'; \
		! $(OBJDUMP) -d build/core0.elf | \
			sed -n '/<kb7_loader_trampoline_relocate_and_enter>:/,/^$$/p' | \
			grep -Eq '\<(push|pop|bl|blx)\>'; \
		! $(OBJDUMP) -d build/core0.elf | \
			sed -n '/<reset_handler>:/,/^$$/p' | grep -q 'core0_main'; \
		! $(NM) build/core0.elf | grep -Eq \
			' (core0_main|kb7_flash_erase_4k|kb7_flash_program|kb7_usb_init|kb7_memcpy)$$'

# Builds the region-1 loader-reentry proof: an image whose only bytes sit at
# the stock region-1 entry 0x1004a524 inside one flash sector, which masks and
# clears every interrupt, takes VTOR, and invokes the stock-equivalent loader
# relocation. Stock region 0 remains the boot path. The separate offline
# campaign builder patches this sector into the exact stock region 1 and
# CRC-balances it. This target emits no bundle and touches no device.
region1-reentry-proof:
	$(MAKE) clean
	$(MAKE) build/region1-reentry-proof.elf PROFILE_DEFINES='-DKB7_ENABLE_UNVERIFIED_LOADER_REENTRY=1 \
		-DKB7_BUILD_LOADER_REENTRY_PROOF=1'
	@set -eu; \
		elf=build/region1-reentry-proof.elf; \
		$(READELF) -r $$elf | grep -q 'There are no relocations'; \
		test -z "`$(NM) -u $$elf`"; \
		entry=`$(READELF) -h $$elf | awk '/Entry point address/ { print $$NF }'`; \
		test "$$entry" = 0x1004a525; \
		text=`$(READELF) -SW $$elf | awk '/ \.text /{ print $$(NF-7) "," $$(NF-5) }'`; \
		test "`printf '%s\n' "$$text" | wc -l`" -eq 1; \
		test "`$(READELF) -SW $$elf | grep -c ' AX '`" -eq 1; \
		start=$$((0x`printf '%s' "$$text" | cut -d, -f1`)); \
		size=$$((0x`printf '%s' "$$text" | cut -d, -f2`)); \
		test $$start -eq $$((0x1004a524)); \
		test $$((start + size)) -le $$((0x1004b000)); \
		$(OBJCOPY) --dump-section \
			.text.kb7_loader_relocator=build/region1-reentry-relocator.bin \
			build/region1-proof/drivers/recovery_trampoline.o; \
		test "`sha256sum build/region1-reentry-relocator.bin | awk '{ print $$1 }'`" = \
			a8c82aa423cc089a563fed7bf2f319f39b2945addf065b47849c04c4d7c793eb; \
		$(OBJCOPY) --dump-section \
			.text.kb7_loader_trampoline=build/region1-reentry-trampoline.bin \
			build/region1-proof/drivers/recovery_trampoline.o; \
		test "`sha256sum build/region1-reentry-trampoline.bin | awk '{ print $$1 }'`" = \
			43bde11ee9089c930b8e67c6b7d569aec736d719f59f24c6b207d80309a2f539; \
		$(OBJCOPY) -O binary $$elf build/region1-reentry-proof.bin; \
		test "`wc -c < build/region1-reentry-proof.bin`" -eq $$size; \
		test "`wc -c < build/region1-reentry-proof.bin`" -eq 404; \
		test "`sha256sum build/region1-reentry-proof.bin | awk '{ print $$1 }'`" = \
			e753380b3c0ce9fb28f69f4d9d066d0877cbd612dedd37149290556420d29356; \
		$(OBJDUMP) -d $$elf | grep -q '60001000'; \
		$(OBJDUMP) -d $$elf | grep -q 'e000ed0c'; \
		$(OBJDUMP) -d $$elf | grep -q '05fa0004'; \
		$(OBJDUMP) -d $$elf | grep -q 'e000ed08'; \
		$(OBJDUMP) -d $$elf | sed -n '/<region1_proof_entry>:/,/^$$/p' | grep -q 'cpsid'; \
		$(OBJDUMP) -d $$elf | sed -n '/<region1_proof_entry>:/,/^$$/p' | grep -q 'msr.*MSP'; \
		! $(NM) $$elf | grep -Eq \
			' (core0_main|core1_entry|kb7_application_main|kb7_flash_erase_4k|kb7_flash_program|kb7_usb_init|kb7_memcpy)$$'

bundle:
	@echo "Installable-bundle generation is intentionally unavailable through this Makefile." >&2
	@echo "The separate offline planner is non-executing and remains flash_approved=false." >&2
	@echo "See ../docs/USB-UPDATER-OFFLINE-DESIGN-2026-08-23.md." >&2
	@exit 2

clean:
	rm -rf build

-include $(DEPS)
