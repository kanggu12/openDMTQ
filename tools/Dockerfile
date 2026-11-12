# syntax=docker/dockerfile:1.7
# ADD --checksum is stable from Dockerfile frontend 1.6 (June 2023); the frontend built into older
# Docker releases has it only in labs. The syntax line (it must stay the first line) has BuildKit
# use 1.7 whatever the Docker version.

# OpenDMTQ tools: content import (7-Zip), APK patching (apktool, signer), QR codes.
# Java for apktool and the signer; pinned to the Ubuntu 24.04 flavour for reproducible builds.
FROM eclipse-temurin:21-jre-noble

# Python runs the tools; qrcode draws the download QR, lz4 reads and writes the client's patch
# tables, Flask and gunicorn serve the admin pages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-qrcode python3-lz4 python3-flask gunicorn python3-pil \
       xz-utils tzdata \
    && rm -rf /var/lib/apt/lists/*

# Pinned releases, verified against the hashes of the copies that were tested.
ADD --chmod=0644 --checksum=sha256:66cf4524a4a45a7f56567d08b2c9b6ec237bcdd78cee69fd4a59c8a0243aeafa \
    https://github.com/iBotPeaches/Apktool/releases/download/v2.12.1/apktool_2.12.1.jar /opt/apktool.jar
ADD --chmod=0644 --checksum=sha256:e1299fd6fcf4da527dd53735b56127e8ea922a321128123b9c32d619bba1d835 \
    https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar /opt/uber-apk-signer.jar
# Official 7-Zip: the distribution's p7zip cannot open RAR5 archives.
ADD --chmod=0644 --checksum=sha256:4ca3b7c6f2f67866b92622818b58233dc70367be2f36b498eb0bdeaaa44b53f4 \
    https://www.7-zip.org/a/7z2501-linux-x64.tar.xz /tmp/7z.tar.xz
# Its license stays in the image with it.
RUN tar -xJf /tmp/7z.tar.xz -C /usr/local/bin 7zz \
    && mkdir -p /usr/local/share/doc/7-zip && tar -xJf /tmp/7z.tar.xz -C /usr/local/share/doc/7-zip License.txt readme.txt \
    && rm /tmp/7z.tar.xz

# The tool package, installed where the system Python finds it even in isolated mode.
COPY opendmtq_tools /usr/lib/python3/dist-packages/opendmtq_tools
# The release this image is (release.yml passes it), for the version the admin pages show when nothing else names one: a
# plain docker run. The command line and the Helm chart pass their own (OPENDMTQ_VERSION), which wins. Empty for an image
# built here. After the package, so that a new number rebuilds no layer above.
ARG OPENDMTQ_VERSION=
ENV OPENDMTQ_VERSION=${OPENDMTQ_VERSION}
# -I keeps Python from importing anything from the mounted, untrusted folders.
# The CLI passes the module to run: opendmtq_tools.patch_apk, .importer or .qr.
ENTRYPOINT ["python3", "-I", "-m"]
