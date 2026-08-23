ENTRY(reset_handler)

MEMORY
{
    IMAGE (rx) : ORIGIN = 0x00000000, LENGTH = 0x0000f35c
    SRAM (rwx) : ORIGIN = 0x18011000, LENGTH = 0x0000d000
}

SECTIONS
{
    .isr_vector : ALIGN(4) { KEEP(*(.isr_vector)) } > IMAGE
    .kb7_pair ORIGIN(IMAGE) + 0x140 : { KEEP(*(.kb7_pair)) } > IMAGE
    .text : ALIGN(4)
    {
        *(.text .text.*)
        KEEP(*(.rodata.usb_descriptors*))
        *(.rodata .rodata.*)
        . = ALIGN(4);
    } > IMAGE
    .data : ALIGN(4)
    {
        __data_start__ = .;
        *(.data .data.*)
        . = ALIGN(4);
        __data_end__ = .;
    } > SRAM AT> IMAGE
    __data_load_start__ = LOADADDR(.data);
    .bss (NOLOAD) : ALIGN(4)
    {
        __bss_start__ = .;
        *(.bss .bss.* COMMON)
        . = ALIGN(4);
        __bss_end__ = .;
    } > SRAM
    /DISCARD/ : { *(.comment) *(.ARM.attributes) *(.note*) *(.eh_frame*) *(.ARM.exidx*) *(.ARM.extab*) }
}

ASSERT(LOADADDR(.data) + SIZEOF(.data) <= ORIGIN(IMAGE) + LENGTH(IMAGE), "core0 image overflow")
ASSERT(__bss_end__ <= ORIGIN(SRAM) + LENGTH(SRAM), "core0 SRAM overflow")
ASSERT(SIZEOF(.isr_vector) == 79 * 4, "core0 vector table must contain 79 entries")
ASSERT(ADDR(.kb7_pair) == ORIGIN(IMAGE) + 0x140, "core0 build-pair marker moved")
ASSERT(SIZEOF(.kb7_pair) == 32, "core0 build-pair marker size changed")
ASSERT(LOADADDR(.data) + SIZEOF(.data) <= ORIGIN(IMAGE) + 0x0000ee00,
       "core0 image overlaps updater fixup reserve")
