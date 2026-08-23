ENTRY(core1_entry)

MEMORY
{
    IMAGE (rx) : ORIGIN = 0x10000000, LENGTH = 0x0006b168
    SRAM (rwx) : ORIGIN = 0x18020000, LENGTH = 0x00018000
}

SECTIONS
{
    .entry : ALIGN(2) { KEEP(*(.entry)) } > IMAGE
    .kb7_pair ORIGIN(IMAGE) + 0x100 : { KEEP(*(.kb7_pair)) } > IMAGE
    .text : ALIGN(4)
    {
        KEEP(*(.text.kb7_host_server_process))
        *(.text .text.*)
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

ASSERT(LOADADDR(.data) + SIZEOF(.data) <= ORIGIN(IMAGE) + LENGTH(IMAGE), "core1 image overflow")
ASSERT(__bss_end__ <= ORIGIN(SRAM) + LENGTH(SRAM), "core1 SRAM overflow")
ASSERT(__bss_end__ + 0x4000 <= 0x1803f5c0, "less than 16 KiB runtime stack headroom")
ASSERT(ADDR(.kb7_pair) == ORIGIN(IMAGE) + 0x100, "core1 build-pair marker moved")
ASSERT(SIZEOF(.kb7_pair) == 32, "core1 build-pair marker size changed")
ASSERT(LOADADDR(.data) + SIZEOF(.data) <= ORIGIN(IMAGE) + 0x0006ac00,
       "core1 image overlaps updater fixup reserve")
