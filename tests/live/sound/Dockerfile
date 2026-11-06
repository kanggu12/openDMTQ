# A browser with a sound card that writes to a file, and what it takes to compare that file with the recording.
FROM zenika/alpine-chrome:with-puppeteer
USER root
# PulseAudio is the sound card, Xvfb the screen: without one, headless Chromium throws its sound away. ffmpeg decodes the
# recording the way Chromium does, numpy compares the two.
RUN apk add --no-cache pulseaudio pulseaudio-utils xvfb python3 py3-numpy ffmpeg
USER chrome
