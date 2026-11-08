// Calls a native method's body the way a Java VM does on a Windows x64 host (Microsoft's x64 calling convention), from
// arguments the VM laid out (NativeArgs in internal.h):
//
//   uint64_t jvm_call_native(void* fn, const uint64_t gpr[4], const uint64_t fpr[4], const uint64_t* stack,
//                            size_t n_stack, uint64_t* fp_result)
//
// The convention gives each of the first four arguments one register by its position: rcx, rdx, r8 or r9 for an
// integer or pointer, xmm0-xmm3 for a float or double. NativeArgs puts each in gpr or fpr at its position; both sets are
// loaded, and the callee reads the one its argument's type says. The rest go on the stack above 32 bytes of home space.
// The integer result comes back in rax; the bits of a float or double result are stored at fp_result.
    .text
    .globl jvm_call_native
    .def jvm_call_native
    .scl 2
    .type 32
    .endef
    .p2align 4
jvm_call_native:
    .seh_proc jvm_call_native
    // rbx, r12 and r13 survive the call (callee-saved here as on System V): they keep fn, fp_result and n_stack.
    push %rbp
    .seh_pushreg %rbp
    push %rbx
    .seh_pushreg %rbx
    push %r12
    .seh_pushreg %r12
    push %r13
    .seh_pushreg %r13
    // Back to a 16-byte boundary: four pushes and the return address are 40 bytes.
    sub $8, %rsp
    .seh_stackalloc 8
    mov %rsp, %rbp
    .seh_setframe %rbp, 0
    .seh_endprologue
    mov %rcx, %rbx
    // The fifth and sixth arguments: above the return address, the 40 bytes pushed and taken here, and the caller's 32
    // bytes of home space.
    mov 80(%rbp), %r13
    mov 88(%rbp), %r12
    // Room for the home space and the stack arguments, down to a 16-byte boundary.
    lea 32(,%r13,8), %rax
    sub %rax, %rsp
    and $-16, %rsp
    // stack[i] goes to 32+i*8(%rsp): the callee finds its fifth argument above its home space.
    xor %r10, %r10
1:
    cmp %r13, %r10
    jae 2f
    mov (%r9,%r10,8), %r11
    mov %r11, 32(%rsp,%r10,8)
    inc %r10
    jmp 1b
2:
    movsd 0(%r8), %xmm0
    movsd 8(%r8), %xmm1
    movsd 16(%r8), %xmm2
    movsd 24(%r8), %xmm3
    // The integer registers last: rdx and r8 held this routine's own arguments up to here.
    mov %rdx, %r10
    mov 0(%r10), %rcx
    mov 8(%r10), %rdx
    mov 16(%r10), %r8
    mov 24(%r10), %r9
    call *%rbx
    movq %xmm0, (%r12)
    mov %rbp, %rsp
    add $8, %rsp
    pop %r13
    pop %r12
    pop %rbx
    pop %rbp
    ret
    .seh_endproc
