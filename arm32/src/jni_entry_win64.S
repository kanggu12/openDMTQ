// Entry of every native method that guest code registered, on a Windows x64 host. The method's stub puts its context
// in r10 and jumps here. Microsoft's x64 convention gives the first four arguments in rcx, rdx, r8 and r9, or in
// xmm0-xmm3 for floating-point ones, each register by the argument's position; the rest lie on the stack above 32 bytes
// of home space. They are saved for arm32_jni_dispatch(context, saved, caller_stack), whose 16-byte result (the integer
// result and the bits of a float or double one) comes back through a pointer it is given first, as that convention
// returns a structure of that size.
    .text
    .globl arm32_jni_entry
    .def arm32_jni_entry
    .scl 2
    .type 32
    .endef
    .p2align 4
arm32_jni_entry:
    .seh_proc arm32_jni_entry
    push %rbp
    .seh_pushreg %rbp
    // Home space for the call (0-31), the result (32-47), rcx, rdx, r8, r9 (48-79), xmm0-xmm3 (80-111): 112 bytes,
    // which keeps the stack 16-byte aligned after the push.
    sub $112, %rsp
    .seh_stackalloc 112
    lea 112(%rsp), %rbp
    .seh_setframe %rbp, 112
    .seh_endprologue
    mov %rcx, 48(%rsp)
    mov %rdx, 56(%rsp)
    mov %r8, 64(%rsp)
    mov %r9, 72(%rsp)
    movsd %xmm0, 80(%rsp)
    movsd %xmm1, 88(%rsp)
    movsd %xmm2, 96(%rsp)
    movsd %xmm3, 104(%rsp)
    // The result's place, the context, the saved registers, and the caller's fifth argument: above the return address,
    // the saved rbp and the 32 bytes of home space.
    lea 32(%rsp), %rcx
    mov %r10, %rdx
    lea 48(%rsp), %r8
    lea 48(%rbp), %r9
    call arm32_jni_dispatch
    mov 32(%rsp), %rax
    movq 40(%rsp), %xmm0
    add $112, %rsp
    pop %rbp
    ret
    .seh_endproc
