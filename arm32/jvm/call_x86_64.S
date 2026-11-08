// Calls a native method's body the way a Java VM does on an x86-64 host with the System V calling convention (Linux;
// macOS names its symbols with a leading underscore and would need its own copy), from arguments the VM laid out
// (NativeArgs in internal.h):
//
//   uint64_t jvm_call_native(void* fn, const uint64_t gpr[6], const uint64_t fpr[8], const uint64_t* stack,
//                            size_t n_stack, uint64_t* fp_result)
//
// gpr holds rdi, rsi, rdx, rcx, r8 and r9; fpr holds xmm0-xmm7 (a float in the low half); stack the arguments that
// did not fit, in order. The integer result comes back in rax; the bits of a float or double result are stored at
// fp_result.
    .text
    .global jvm_call_native
    .type jvm_call_native, @function
    .balign 16
jvm_call_native:
    push %rbp
    mov %rsp, %rbp
    // rbx and r12 survive the call (callee-saved): they keep fn and fp_result.
    push %rbx
    push %r12
    mov %rdi, %rbx
    mov %r9, %r12
    // Room for the stack arguments, then down to a 16-byte boundary, which the call needs.
    mov %r8, %rax
    shl $3, %rax
    sub %rax, %rsp
    and $-16, %rsp
    // stack[i] goes to i*8(%rsp): the callee finds its first stack argument just above its return address.
    xor %r10, %r10
1:
    cmp %r8, %r10
    jae 2f
    mov (%rcx,%r10,8), %r11
    mov %r11, (%rsp,%r10,8)
    inc %r10
    jmp 1b
2:
    // The vector registers, whole: a float's bits are in the low half already.
    movsd 0(%rdx), %xmm0
    movsd 8(%rdx), %xmm1
    movsd 16(%rdx), %xmm2
    movsd 24(%rdx), %xmm3
    movsd 32(%rdx), %xmm4
    movsd 40(%rdx), %xmm5
    movsd 48(%rdx), %xmm6
    movsd 56(%rdx), %xmm7
    // The integer registers last: rsi, rdx and rcx hold this routine's own arguments up to here.
    mov %rsi, %r10
    mov 0(%r10), %rdi
    mov 8(%r10), %rsi
    mov 16(%r10), %rdx
    mov 24(%r10), %rcx
    mov 32(%r10), %r8
    mov 40(%r10), %r9
    // al bounds the vector registers in use; only variadic functions read it, and 8 is never too few.
    mov $8, %eax
    call *%rbx
    movq %xmm0, (%r12)
    // Back to just below the two saved registers, whatever the stack arguments took.
    lea -16(%rbp), %rsp
    pop %r12
    pop %rbx
    pop %rbp
    ret
    .size jvm_call_native, . - jvm_call_native
    .section .note.GNU-stack, "", @progbits
