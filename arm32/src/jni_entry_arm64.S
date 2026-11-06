// Entry of every native method that guest code registered (64-bit ARM host). The method's stub
// puts its context in x16 and jumps here. The argument registers are saved for
// arm32_jni_dispatch(context, saved, caller_stack), whose two-word result is the integer
// result and the bits of a float or double result.
    .text
    .global arm32_jni_entry
    .type arm32_jni_entry, %function
    .balign 16
arm32_jni_entry:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    // x0-x7, then d0-d7.
    sub sp, sp, #128
    stp x0, x1, [sp, #0]
    stp x2, x3, [sp, #16]
    stp x4, x5, [sp, #32]
    stp x6, x7, [sp, #48]
    stp d0, d1, [sp, #64]
    stp d2, d3, [sp, #80]
    stp d4, d5, [sp, #96]
    stp d6, d7, [sp, #112]
    mov x0, x16
    mov x1, sp
    // Arguments that did not fit in registers start above the saved frame record.
    add x2, x29, #16
    bl arm32_jni_dispatch
    fmov d0, x1
    mov sp, x29
    ldp x29, x30, [sp], #16
    ret
    .size arm32_jni_entry, . - arm32_jni_entry
    .section .note.GNU-stack, "", %progbits
