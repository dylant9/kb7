/*
 * Region-1 loader-reentry proof.
 *
 * Stock region 0 stays installed and calls the fixed Thumb entry
 * 0x1004a525 (see docs/STOCK-CORE0-REGION1-CONTRACT-2026-09-05.md).  This
 * image therefore places its only file-backed bytes at that entry inside the
 * one region-1 flash sector 0x0004a000..0x0004b000 (region-1 offsets); the
 * fixed campaign patches that sector into the otherwise exact stock region 1
 * and CRC-balances it to the unchanged manifest checksum.
 */
ENTRY(region1_proof_entry)

MEMORY
{
    PATCH (rx) : ORIGIN = 0x1004a524, LENGTH = 0x00000adc
    SRAM (rwx) : ORIGIN = 0x18030000, LENGTH = 0x00004000
}

SECTIONS
{
    .text : ALIGN(4)
    {
        KEEP(*(.entry))
        *(.text .text.*)
        *(.rodata .rodata.*)
        . = ALIGN(4);
    } > PATCH
    .data : ALIGN(4)
    {
        __data_start__ = .;
        *(.data .data.*)
        . = ALIGN(4);
        __data_end__ = .;
    } > SRAM AT> PATCH
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

ASSERT(ADDR(.text) == 0x1004a524, "region-1 proof entry moved from the stock entry")
ASSERT(LOADADDR(.data) + SIZEOF(.data) <= 0x1004b000, "region-1 proof escapes its patch sector")
ASSERT(SIZEOF(.data) == 0, "region-1 proof must not carry initialized data")
ASSERT(SIZEOF(.bss) == 0, "region-1 proof must not carry zero-initialized data")
