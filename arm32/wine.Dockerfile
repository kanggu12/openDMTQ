# The Windows builds' tests on Linux (arm32/test_windows.sh): WineHQ's Wine at the fixed version tests/windows/wine.sh
# has, with what the player's parts need of a desktop: an X server in memory (Xvfb) and Mesa's OpenGL, on which Wine's
# Direct3D runs and ANGLE on it; GStreamer's decoders, which Wine's Media Foundation decodes H.264 and AAC with;
# PulseAudio, under Wine's WASAPI; FFmpeg's tool for the test video; and a Korean locale, from which Wine makes its
# user's locale a Korean Windows's (the player's language checks).
FROM debian:12
RUN dpkg --add-architecture i386 && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      --no-install-recommends ca-certificates curl gnupg >/dev/null \
    && mkdir -pm755 /etc/apt/keyrings \
    && curl -fsSL https://dl.winehq.org/wine-builds/winehq.key | gpg --dearmor -o /etc/apt/keyrings/winehq-archive.key \
    && curl -fsSL -o /etc/apt/sources.list.d/winehq-bookworm.sources \
      https://dl.winehq.org/wine-builds/debian/dists/bookworm/winehq-bookworm.sources \
    && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --install-recommends \
      winehq-stable=11.0.0.0~bookworm-1 wine-stable=11.0.0.0~bookworm-1 wine-stable-amd64=11.0.0.0~bookworm-1 \
      wine-stable-i386=11.0.0.0~bookworm-1 >/dev/null \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends xvfb xauth libgl1-mesa-dri libglx-mesa0 \
      libgl1 gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav pulseaudio \
      pulseaudio-utils ffmpeg locales >/dev/null \
    && localedef -i ko_KR -c -f UTF-8 ko_KR.UTF-8 \
    && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/wine-stable/bin:$PATH
