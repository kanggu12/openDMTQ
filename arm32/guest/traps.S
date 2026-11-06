// Calls into the host runtime: each stub puts its number in r7 and traps with svc. r7 is
// callee-saved in the ARM procedure call standard, so it is kept on the stack meanwhile.
    .syntax unified
    .arm
    .text

.macro trap name, number
    .global \name
    .type \name, %function
    .balign 4
\name:
    push {r7, lr}
    movw r7, #(\number & 0xffff)
    movt r7, #(\number >> 16)
    svc #0
    pop {r7, pc}
    .size \name, . - \name
.endm

    trap arm32_ready, 0x00f0f001
    trap arm32_next_request, 0x00f0f002
    trap arm32_park, 0x00f0f003
    trap arm32_created, 0x00f0f004
