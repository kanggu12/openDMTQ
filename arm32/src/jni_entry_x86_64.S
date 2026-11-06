// Entry of every native method that guest code registered (x86-64 host, for the emulator). The
// method's stub puts its context in r10 and jumps here. The argument registers are saved for
// arm32_jni_dispatch(context, saved, caller_stack), whose two-word result is the integer
// result and the bits of a float or double result.
    .text
    .global arm32_jni_entry
    .type arm32_jni_entry, @function
    .balign 16
arm32_jni_entry:
    push %rbp
    mov %rsp, %rbp
    // rdi, rsi, rdx, rcx, r8, r9, then xmm0-xmm7; 112 bytes keeps the stack 16-byte aligned.
    sub $112, %rsp
    mov %rdi, 0(%rsp)
    mov %rsi, 8(%rsp)
    mov %rdx, 16(%rsp)
    mov %rcx, 24(%rsp)
    mov %r8, 32(%rsp)
    mov %r9, 40(%rsp)
    movsd %xmm0, 48(%rsp)
    movsd %xmm1, 56(%rsp)
    movsd %xmm2, 64(%rsp)
    movsd %xmm3, 72(%rsp)
    movsd %xmm4, 80(%rsp)
    movsd %xmm5, 88(%rsp)
    movsd %xmm6, 96(%rsp)
    movsd %xmm7, 104(%rsp)
    mov %r10, %rdi
    mov %rsp, %rsi
    // Arguments that did not fit in registers start above the return address and saved rbp.
    lea 16(%rbp), %rdx
    call arm32_jni_dispatch
    movq %rdx, %xmm0
    leave
    ret
    .size arm32_jni_entry, . - arm32_jni_entry
    .section .note.GNU-stack, "", @progbits
