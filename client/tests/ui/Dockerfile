# The launcher's UI test machine: Linux Python with Tk, a virtual X screen and screenshot tools. It also draws the
# Windows build's pictures (client/packaging/windows/assets.py). Nothing here reaches a real screen; the tests run with
# OPENDMTQ_VIRTUAL_DISPLAY=1 only inside it.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
        libtk8.6 tk8.6 xvfb x11-utils xdotool imagemagick fontconfig \
    && rm -rf /var/lib/apt/lists/*
# Pillow draws the pictures; fontTools reads the icon font for the unit tests (each icon has its glyph).
RUN pip install --no-cache-dir pillow==11.3.0 fonttools==4.55.3
ENV OPENDMTQ_VIRTUAL_DISPLAY=1 DISPLAY=:99
