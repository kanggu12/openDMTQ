// What the VM's own files share and the library's users do not need: the classes the VM itself makes, references,
// signatures, strings, and native calls.
#pragma once

#include "jvm.h"

#include <map>

namespace jvm {

// Classes the VM itself makes objects of, found once.
struct Core {
    Class* object = nullptr;
    Class* class_class = nullptr;
    Class* string = nullptr;
    Class* throwable = nullptr;
    Class* null_pointer = nullptr;
    Class* method = nullptr;
    Class* constructor = nullptr;
    Class* field = nullptr;
    Class* proxy = nullptr;
    Class* direct_buffer = nullptr;
    // java.lang.Integer for 'I', and so on.
    std::map<char, Class*> boxes;
    // int.class for 'I', and so on ('V' too).
    std::map<char, Class*> primitives;
};
const Core& core();

// The JNI function tables (jni.cpp).
extern const JNINativeInterface kNativeInterface;
extern const JNIInvokeInterface kInvokeInterface;

// Sets an object's class: the registry needs it for java/lang/Class, which is its own class.
void set_class(Object& o, Class* cls);

// A method signature read into m (params, param_types, ret_type, ret), false if it is malformed.
bool parse_signature(std::string_view sig, Method& m);

// UTF-8 or modified UTF-8 to UTF-16, and UTF-16 to modified UTF-8.
std::u16string utf16_of(std::string_view s);
std::string mutf8_of(const char16_t* chars, std::size_t n);

// A new object of cls (made by the nearest class up its chain that makes its own kind), not yet constructed.
Object* instantiate(Class& cls);

// A static field's value, read and written under the fields lock.
Value static_value(const Field* f);
void set_static_value(Field* f, const Value& v);

// A Throwable's message (its detailMessage field), "" when it has none.
std::string message_of(Object* throwable);

// Global and weak global references, and the kind of any reference.
jobject new_global(Object* o, bool weak);
void delete_global(jobject g);
std::size_t global_count();
jobjectRefType ref_type(jobject r);

// What a method nothing implements returns (vm.cpp says why): an object of its return class, an empty array, or zero.
Value inert_result(Method& m);

// Calls a native method's body fn through the platform's calling convention, in a local frame of its own.
Value call_native(Env& e, Method& m, void* fn, Object* self, const Value* args, std::size_t n);

// The arguments of a native call in the order the platform passes them: integer and pointer registers, vector
// registers, then the stack, each argument taking the next free one of its kind (System V AMD64).
struct NativeArgs {
#ifdef _WIN32
    // Microsoft's x64 convention: four argument registers, each position either an integer one or a vector one.
    static constexpr int kIntRegs = 4, kFloatRegs = 4;
#else
    // System V: six integer registers and eight vector ones, each kind counted on its own.
    static constexpr int kIntRegs = 6, kFloatRegs = 8;
#endif
    std::uint64_t gpr[kIntRegs] = {};
    std::uint64_t fpr[kFloatRegs] = {};
    std::vector<std::uint64_t> stack;
    int n_gpr = 0, n_fpr = 0;
    void integer(std::uint64_t v);
    void floating(std::uint64_t bits);
};

// call_x86_64.S (System V) or call_win64.S (Windows x64): calls fn with these registers and stack words; returns the
// integer result, and stores the vector result's bits at fp_result.
extern "C" std::uint64_t jvm_call_native(void* fn, const std::uint64_t* gpr, const std::uint64_t* fpr, const std::uint64_t* stack,
                                         std::size_t n_stack, std::uint64_t* fp_result);

// The one class loader (lang.cpp): every class has it.
Object* system_loader();
// Class.getMethod and its kin: the method of cls (or a superclass, for methods) with that name and those parameter
// classes; NoSuchMethodException when none has it.
Ref<Object> reflect_method(Class& cls, const std::string& name, Array* params, bool constructor);

// ARM32_TRACE in the environment: the VM logs what it makes up as well.
bool trace_on();

}  // namespace jvm
