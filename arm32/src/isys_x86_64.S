// A host system call that cannot miss a guest signal (x86-64 host, for the emulator).
//
//   long arm32_isys(long a0, long a1, long a2, long a3, long a4, long a5, const IsysGate* gate)
//
// The gate holds the address of the guest thread's pending signals, the signals it blocks and the
// call number. A signal that is already ready skips the call (-EINTR). The interrupt signal
// Process::send_signal sends after making one pending either cuts the call short (-EINTR) or, when
// it lands between the check and the syscall, finds its pc in [arm32_isys_begin, arm32_isys_end)
// and moves it to arm32_isys_cancel if a signal is still ready. The handler finds the gate at
// 8(%rsp) for that check: the stack pointer must not move between the label and the syscall.
    .text
    .global arm32_isys, arm32_isys_begin, arm32_isys_end, arm32_isys_cancel
    .type arm32_isys, @function
    .balign 16
arm32_isys:
    // The gate is the seventh argument, on the stack above the return address.
    mov 8(%rsp), %r11
    // The kernel takes the fourth argument in r10 and the call number in rax.
    mov %rcx, %r10
    mov 16(%r11), %rax
arm32_isys_begin:
    // pending & ~blocked: a signal that is ready means no call. rcx and r11 are free: the
    // syscall instruction overwrites them anyway.
    mov 0(%r11), %rcx
    mov (%rcx), %rcx
    mov 8(%r11), %r11
    not %r11
    test %r11, %rcx
    jnz arm32_isys_cancel
    syscall
arm32_isys_end:
    ret
arm32_isys_cancel:
    mov $-4, %rax
    ret
    .size arm32_isys, . - arm32_isys
    .section .note.GNU-stack, "", @progbits
