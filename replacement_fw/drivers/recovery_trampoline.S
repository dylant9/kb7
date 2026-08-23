/*
 * Independently authored equivalent of the stock loader-relocation sequence.
 *
 * This routine is copied to the established executable stack SRAM before it
 * is called.  It must not execute from Core-0 PRAM because its copy loop
 * replaces that entire 64-KiB window with the preserved flash loader.
 */

    .syntax unified
    .cpu cortex-m3
    .thumb

/*
 * Stackless relocation bridge.
 *
 * r0 is the source blob and r1 its checked byte length.  This function samples
 * MSP only after all compiler-generated caller state exists, places the blob
 * below that exact value, copies without touching SP, and never returns.
 */
    .section .text.kb7_loader_relocator, "ax", %progbits
    .balign 4
    .global kb7_loader_trampoline_relocate_and_enter
    .type kb7_loader_trampoline_relocate_and_enter, %function
    .thumb_func
kb7_loader_trampoline_relocate_and_enter:
    cpsid   i
    cmp     r1, #0
    beq     .Lrelocate_fail
    cmp     r1, #192
    bhi     .Lrelocate_fail
    adds    r2, r1, #64
    cmp.w   r2, #256
    bhi     .Lrelocate_fail

    mrs     r2, msp
    ldr     r3, .Lstack_floor
    cmp     r2, r3
    blo     .Lrelocate_fail
    ldr     r3, .Lstack_top
    cmp     r2, r3
    bhi     .Lrelocate_fail

    sub.w   r2, r2, #256
    bic.w   r2, r2, #3
    mov     r12, r2
.Lrelocate_copy:
    ldrb    r3, [r0], #1
    strb    r3, [r2], #1
    subs    r1, #1
    bne     .Lrelocate_copy

    dsb     sy
    isb     sy
    orr.w   r12, r12, #1
    bx      r12

.Lrelocate_fail:
    wfi
    b       .Lrelocate_fail

    .balign 4
.Lstack_floor:
    .word   0x1803e000
.Lstack_top:
    .word   0x1803f5c0
    .size kb7_loader_trampoline_relocate_and_enter, \
        . - kb7_loader_trampoline_relocate_and_enter

    .section .text.kb7_loader_trampoline, "ax", %progbits
    .balign 4
    .global kb7_loader_trampoline_blob_start
    .global kb7_loader_trampoline_blob_end
    .global kb7_loader_trampoline_start
    .type kb7_loader_trampoline_blob_start, %object
    .type kb7_loader_trampoline_start, %function
kb7_loader_trampoline_blob_start:
    .thumb_func
kb7_loader_trampoline_start:
    mov     r1, pc
    cmp.w   r1, #0x10000
    blo     .Lunsafe_location

    cpsid   i
    movs    r0, #0
    ldr     r3, .Lloader_source
    ldr     r1, .Lloader_length
.Lcopy_loader:
    ldr     r2, [r3, r0]
    str     r2, [r0]
    adds    r0, #4
    cmp     r0, r1
    blo     .Lcopy_loader

    dsb     sy
    ldr     r0, .Laircr_address
    ldr     r1, [r0]
    and.w   r1, r1, #0x700
    ldr     r2, .Laircr_request
    orrs    r1, r2
    str     r1, [r0]
    dsb     sy
.Lreset_wait:
    b       .Lreset_wait

.Lunsafe_location:
    cpsid   i
    b       .Lunsafe_location

    .balign 4
.Lloader_source:
    .word   0x60001000
.Lloader_length:
    .word   0x00010000
.Laircr_address:
    .word   0xe000ed0c
.Laircr_request:
    .word   0x05fa0004
kb7_loader_trampoline_blob_end:
    .size kb7_loader_trampoline_start, . - kb7_loader_trampoline_start
    .size kb7_loader_trampoline_blob_start, . - kb7_loader_trampoline_blob_start

    .section .note.GNU-stack, "", %progbits
