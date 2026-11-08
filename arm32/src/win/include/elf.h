// <elf.h> on Windows: the 32-bit ELF structures the loader reads, as the ELF specification defines them (the constants
// come from Linux's own header through arm32_linux_abi.h).
#pragma once

#include <arm32_linux.h>

#include <cstdint>

typedef std::uint32_t Elf32_Addr;
typedef std::uint16_t Elf32_Half;
typedef std::uint32_t Elf32_Off;
typedef std::int32_t Elf32_Sword;
typedef std::uint32_t Elf32_Word;

#define EI_NIDENT 16

typedef struct {
    unsigned char e_ident[EI_NIDENT];
    Elf32_Half e_type, e_machine;
    Elf32_Word e_version;
    Elf32_Addr e_entry;
    Elf32_Off e_phoff, e_shoff;
    Elf32_Word e_flags;
    Elf32_Half e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx;
} Elf32_Ehdr;

typedef struct {
    Elf32_Word p_type;
    Elf32_Off p_offset;
    Elf32_Addr p_vaddr, p_paddr;
    Elf32_Word p_filesz, p_memsz, p_flags, p_align;
} Elf32_Phdr;

typedef struct {
    Elf32_Sword d_tag;
    union {
        Elf32_Word d_val;
        Elf32_Addr d_ptr;
    } d_un;
} Elf32_Dyn;

typedef struct {
    Elf32_Word st_name;
    Elf32_Addr st_value;
    Elf32_Word st_size;
    unsigned char st_info, st_other;
    Elf32_Half st_shndx;
} Elf32_Sym;

// A section header: the bridge reads the dynamic symbols' table through them.
typedef struct {
    Elf32_Word sh_name, sh_type, sh_flags;
    Elf32_Addr sh_addr;
    Elf32_Off sh_offset;
    Elf32_Word sh_size, sh_link, sh_info, sh_addralign, sh_entsize;
} Elf32_Shdr;

// A symbol's binding is the high four bits of st_info, its type the low four.
#define ELF32_ST_BIND(info) ((info) >> 4)
#define ELF32_ST_TYPE(info) ((info) & 0xf)
#define ELF32_ST_INFO(bind, type) (((bind) << 4) + ((type) & 0xf))

typedef struct {
    Elf32_Addr r_offset;
    Elf32_Word r_info;
} Elf32_Rel;

typedef struct {
    Elf32_Word a_type;
    union {
        Elf32_Word a_val;
    } a_un;
} Elf32_auxv_t;
