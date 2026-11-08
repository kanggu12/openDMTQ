// Read before every C++ file of the desktop player: the NDK's headers mark each declaration with the API level that
// added it, and on a phone bionic's sys/cdefs.h brings in the macros that do it; a desktop host's C library does not.
#pragma once

// The attribute macros first: api-level.h uses them on its own declarations.
#include <android/versioning.h>
#include <android/api-level.h>
