# The shim for phones that run the game's 32-bit libraries themselves: see shim.cpp.
cmake_minimum_required(VERSION 3.18)
project(opendmtq_shim CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(opendmtq SHARED shim.cpp ../src/live.cpp ../src/live_net.cpp ../src/live_ts.cpp ../src/pacing.cpp ../src/follow.cpp ../src/window_rate.cpp)
target_include_directories(opendmtq PRIVATE ../src)
target_compile_definitions(opendmtq PRIVATE ARM32_SHIM)
target_compile_options(opendmtq PRIVATE -Wall -Wextra -Wno-unused-parameter -Wno-unused-function -fvisibility=hidden)
target_link_libraries(opendmtq PRIVATE android log)
target_link_options(opendmtq PRIVATE -Wl,--exclude-libs,ALL -Wl,-z,max-page-size=16384)
