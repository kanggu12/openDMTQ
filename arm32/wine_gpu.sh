# shellcheck shell=bash
# Which renderer a Wine run of the player for Windows draws with, sourced by client/tests/windows/e2e.sh: on this side
# for the image and docker run's arguments, and in its container (mounted as /wine_gpu.sh) for the check.
#   unset (the default, and CI's)   arm32/wine.Dockerfile's image: Mesa's llvmpipe draws every frame on the CPU
#   OPENDMTQ_WINE_GPU=1             arm32/wine-gpu.Dockerfile's image (the same with Mesa 25, whose d3d12 driver has
#                                   what Wine's Direct3D 11 needs) with WSL's GPU handed to the container: the player's
#                                   frames are drawn on this PC's graphics card, each read back to the virtual screen
# The GPU needs WSL 2 with the graphics card's Windows driver: /dev/dxg, /usr/lib/wsl/lib (WSL's D3D12 and DXCore
# libraries) and /usr/lib/wsl/drivers (the card's own user-mode driver, which WSL's D3D12 loads from there). The player
# is a 64-bit program, so Wine's 64-bit side and Mesa's 64-bit driver are all it uses. Nothing is drawn on the Windows
# desktop: the container's virtual screen is the only one it has. OPENDMTQ_WINE_GPU_TAG names the GPU images' tag
# (local by default), so that two checkouts' runs keep their own.
#
#   wine_gpu_e2e_image   the PC client's end to end image: opendmtq-client-e2e:local, or its twin on the GPU image
#                        (client/tests/windows/Dockerfile on arm32/wine-gpu.Dockerfile's image, each built the first time)
#   WINE_GPU_ARGS        docker run's arguments for the renderer (none on the CPU)
# Inside the container the virtual screen starts as `env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb`: Xvfb only shows what
# it is sent, and with WSL's variables its own OpenGL would open a D3D12 device it never uses (on the CPU the variables
# are not set and the command is plain Xvfb). There, on the GPU (WINE_GPU_IN_CONTAINER is set):
#   wine_gpu_proof       whether the player's own process (its first argument ends in OpenDMTQ-Player.exe) draws through
#                        WSL's D3D12, its memory holding WSL's libd3d12 and /dev/dxg open, and what the container's
#                        OpenGL is; the finding printed, 1 when it does not (so a GPU run that fell back to the CPU fails)

# The GPU images' names, a checkout's own when it gives a tag.
WINE_GPU_TAG=${OPENDMTQ_WINE_GPU_TAG:-local}
WINE_GPU_IMAGE=opendmtq-arm32-wine-gpu:$WINE_GPU_TAG
WINE_GPU_E2E_IMAGE=opendmtq-client-e2e-gpu:$WINE_GPU_TAG

wine_on_gpu() { [ "${OPENDMTQ_WINE_GPU:-}" = 1 ]; }

# This side's part (the container sources this file for the proof alone).
if [ -z "${WINE_GPU_IN_CONTAINER:-}" ]; then
  # The recipes: wine-gpu.Dockerfile beside this file, the end to end's in client/tests/windows.
  WINE_GPU_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  WINE_GPU_ARGS=()
  if wine_on_gpu; then
    # WSL's GPU: its device, its libraries and the card's driver store, read only, and Mesa told to draw through D3D12
    # (WSLg sets the same two variables); Mesa finds libd3d12.so and libdxcore.so on LD_LIBRARY_PATH.
    for need in /dev/dxg /usr/lib/wsl/lib/libd3d12.so /usr/lib/wsl/lib/libdxcore.so /usr/lib/wsl/drivers; do
      [ -e "$need" ] || { echo "FAIL: OPENDMTQ_WINE_GPU=1 needs WSL's GPU ($need is missing)" >&2; exit 1; }
    done
    WINE_GPU_ARGS=(--device /dev/dxg -v /usr/lib/wsl/lib:/usr/lib/wsl/lib:ro -v /usr/lib/wsl/drivers:/usr/lib/wsl/drivers:ro
                   -e LD_LIBRARY_PATH=/usr/lib/wsl/lib -e GALLIUM_DRIVER=d3d12 -e WINE_GPU_IN_CONTAINER=1)
    # No core dumps: WSL's crash capture writes each one into Windows' temporary folder (a limit of 1 is the kernel's
    # sign to skip a dump that goes to a program).
    WINE_GPU_ARGS+=(--ulimit core=1)
  fi
fi

wine_gpu_e2e_image() {
  # On the CPU: the image the end to end has always used.
  wine_on_gpu || { echo opendmtq-client-e2e:local; return 0; }
  # The GPU image on the CPU one (made first when it is not there yet), then the end to end's tools on it. Its Mesa is
  # fetched once, from Debian's backports.
  docker image inspect opendmtq-arm32-wine >/dev/null 2>&1 \
    || docker build -q -t opendmtq-arm32-wine -f "$WINE_GPU_DIR/wine.Dockerfile" "$WINE_GPU_DIR" >/dev/null
  docker image inspect "$WINE_GPU_IMAGE" >/dev/null 2>&1 \
    || docker build -q -t "$WINE_GPU_IMAGE" -f "$WINE_GPU_DIR/wine-gpu.Dockerfile" "$WINE_GPU_DIR" >/dev/null \
    || { echo "FAIL: the GPU image did not build" >&2; return 1; }
  docker image inspect "$WINE_GPU_E2E_IMAGE" >/dev/null 2>&1 \
    || docker build -q -t "$WINE_GPU_E2E_IMAGE" --build-arg "BASE=$WINE_GPU_IMAGE" "$WINE_GPU_DIR/../client/tests/windows" >/dev/null \
    || { echo "FAIL: the GPU end to end image did not build" >&2; return 1; }
  echo "$WINE_GPU_E2E_IMAGE"
}

wine_gpu_proof() {
  # Only in a container on the GPU.
  [ -n "${WINE_GPU_IN_CONTAINER:-}" ] || return 0
  local d first d3d12 dxg fd renderer
  # What the container's OpenGL is, in Mesa's own words (the player's Direct3D 11 reaches it through Wine), and the
  # version of the 64-bit Mesa the player uses.
  renderer=$(glxinfo -B 2>/dev/null | sed -n 's/^OpenGL renderer string: //p' | head -n 1)
  echo "the container's OpenGL: ${renderer:-none}, Mesa $(dpkg-query -W -f '${Version}' libgl1-mesa-dri:amd64 2>/dev/null)"
  for d in /proc/[0-9]*; do
    # The player's own process: Wine gives it its Windows command line, the program first.
    first=$(tr '\0' '\n' < "$d/cmdline" 2>/dev/null | head -n 1)
    case "$first" in *OpenDMTQ-Player.exe) ;; *) continue ;; esac
    # WSL's D3D12 library in its memory: Mesa's d3d12 driver loaded it in this process (llvmpipe never does).
    d3d12=$(grep -c /usr/lib/wsl/lib/libd3d12 "$d/maps" 2>/dev/null)
    # Its open files that are WSL's GPU device.
    dxg=0
    for fd in "$d"/fd/*; do
      [ "$(readlink "$fd" 2>/dev/null)" = /dev/dxg ] && dxg=$((dxg + 1))
    done
    # Both: the card draws its frames.
    if [ "${d3d12:-0}" -gt 0 ] && [ "${dxg:-0}" -gt 0 ]; then
      echo "the player draws on the GPU: its process ${d#/proc/} has WSL's libd3d12 in its memory and /dev/dxg open"
      return 0
    fi
  done
  # None: Mesa fell back to drawing on the CPU (or the player is gone), which a GPU run must not pass as.
  echo "FAIL: the player does not draw on the GPU: no process of OpenDMTQ-Player.exe has WSL's libd3d12 and /dev/dxg"
  return 1
}
