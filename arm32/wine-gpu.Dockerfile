# The player's Wine image (arm32/wine.Dockerfile) for runs drawn on a WSL machine's own graphics card
# (OPENDMTQ_WINE_GPU=1, arm32/wine_gpu.sh): the same Wine, virtual screen, sound and decoders, with a newer Mesa. The
# image wine.Dockerfile makes stays the default and the one CI uses.
#
# Why a newer Mesa: the player is a 64-bit program, so its OpenGL is Mesa's 64-bit one, whose d3d12 driver hands each
# call to the graphics card through WSL's /dev/dxg. Debian 12's Mesa (22.3) has that driver at OpenGL 4.2 without
# ARB_polygon_offset_clamp, and Wine's Direct3D needs it for feature level 10 and up: ANGLE then finds no Direct3D 11
# device, and the game no OpenGL ES. Debian's backports for the same release have Mesa 25, whose d3d12 driver is at
# OpenGL 4.6 with it. The rest stays the release's: the two images differ in Mesa (with what Mesa 25 needs from the
# backports, its LLVM among them) and in glxinfo.
#
#   docker build -t opendmtq-arm32-wine-gpu:local -f arm32/wine-gpu.Dockerfile arm32   (after wine.Dockerfile's image)
#
# Run with WSL's GPU (wine_gpu.sh does this): --device /dev/dxg, /usr/lib/wsl/lib and /usr/lib/wsl/drivers read only,
# LD_LIBRARY_PATH=/usr/lib/wsl/lib and GALLIUM_DRIVER=d3d12. Without them it draws with Mesa 25's llvmpipe.
FROM opendmtq-arm32-wine
# Mesa from the release's backports for both of Wine's halves (Debian keeps a library's two architectures at one
# version), and glxinfo, which says what renderer the container's OpenGL has. One layer, and no package lists kept.
RUN echo "deb http://deb.debian.org/debian bookworm-backports main" > /etc/apt/sources.list.d/bookworm-backports.list \
    && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends -t bookworm-backports \
      libgl1-mesa-dri libglx-mesa0 libegl-mesa0 libgbm1 mesa-libgallium \
      libgl1-mesa-dri:i386 libglx-mesa0:i386 libegl-mesa0:i386 libgbm1:i386 mesa-libgallium:i386 mesa-utils >/dev/null \
    && rm -rf /var/lib/apt/lists/*
# Refused at build time when the Mesa installed is older than the 25 the driver needs to be at (a backports line that
# went back would build an image that draws nothing on the GPU).
RUN v=$(dpkg-query -W -f '${Version}' libgl1-mesa-dri:amd64) && echo "Mesa $v" && [ "${v%%.*}" -ge 25 ]
