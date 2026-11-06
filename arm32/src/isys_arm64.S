// A host system call that cannot miss a guest signal (64-bit ARM host).
//
//   long arm32_isys(long a0, long a1, long a2, long a3, long a4, long a5, const IsysGate* gate)
//
// The gate holds the address of the guest thread's pending signals, the signals it blocks and the
// call number. A signal that is already ready skips the call (-EINTR). The interrupt signal
// Process::send_signal sends after making one pending either cuts the call short (-EINTR) or, when
// it lands between the check and the svc, finds its pc in [arm32_isys_begin, arm32_isys_end) and
// moves it to arm32_isys_cancel if a signal is still ready. The handler finds the gate in x6 for
// that check: x6 must keep it up to the svc.
    .text
    .global arm32_isys, arm32_isys_begin, arm32_isys_end, arm32_isys_cancel
    .type arm32_isys, %function
    .balign 16
arm32_isys:
    // The call number goes in x8; the arguments are already in x0-x5.
    ldr x8, [x6, #16]
arm32_isys_begin:
    // pending & ~blocked: a signal that is ready means no call.
    ldr x9, [x6]
    ldar x9, [x9]
    ldr x10, [x6, #8]
    bics xzr, x9, x10
    b.ne arm32_isys_cancel
    svc #0
arm32_isys_end:
    ret
arm32_isys_cancel:
    mov x0, #-4
    ret
    .size arm32_isys, . - arm32_isys
    .section .note.GNU-stack, "", %progbits
