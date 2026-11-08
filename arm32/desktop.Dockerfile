# Build environment for the arm32 runtime on a desktop Linux host (glibc), the first step towards players' clients
# that need no phone: Clang, CMake and Ninja, the Boost headers Dynarmic wants, the EGL, GLES, X11 and zlib headers the
# desktop player builds with, and to run it with no screen, Mesa's software renderer and a virtual X server (Xvfb); the
# PulseAudio headers its sound output is written against, and a PulseAudio server with its tools, which the sound tests
# record what the player plays from; FFmpeg, whose libraries the player decodes video with, and whose tool makes the
# test videos.
FROM ubuntu:24.04
# One layer, and no package lists kept: the image only builds and runs the runtime's tests.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      clang cmake ninja-build python3 git file make libboost-dev libegl-dev libgles-dev libx11-dev zlib1g-dev \
      libegl-mesa0 libgl1-mesa-dri xvfb xauth ca-certificates libpulse-dev pulseaudio pulseaudio-utils ffmpeg && \
    rm -rf /var/lib/apt/lists/*
# The repository is mounted here.
WORKDIR /r
