#!/bin/sh
# The sound card, in a container of its own: whatever load the browser is under must not reach what records it.
set -eu
export XDG_RUNTIME_DIR=/tmp/xdg HOME=/tmp/home
mkdir -p "$XDG_RUNTIME_DIR" "$HOME/.config/pulse"
chmod 700 "$XDG_RUNTIME_DIR"
# Everything at the stream's own rate. Left at PulseAudio's default of 44.1 kHz, the browser and the card each resample,
# and a clean playback differs from the recording enough to look like damage.
cat > "$HOME/.config/pulse/daemon.conf" <<CONF
default-sample-rate = 48000
alternate-sample-rate = 48000
default-sample-format = s16le
avoid-resampling = yes
CONF
# A sink that plays to nowhere, reachable through a socket in the shared folder, by anyone in the test.
pulseaudio -D --exit-idle-time=-1 --disallow-exit -n --realtime=no \
    -L "module-native-protocol-unix auth-anonymous=1 socket=/sock/native" \
    -L "module-null-sink sink_name=card rate=48000 channels=2"
export PULSE_SERVER=unix:/sock/native
# Waits for the socket: the daemon returns before it listens.
for _ in 1 2 3 4 5 6 7 8 9 10; do pactl info >/dev/null 2>&1 && break; sleep 0.5; done
pactl set-default-sink card
# Records what the sink plays until the test says it is over.
parec -d card.monitor --format=s16le --rate=48000 --channels=2 --latency-msec=50 > /out/heard.raw &
recorder=$!
touch /sock/ready
while [ ! -e /sock/stop ]; do sleep 0.2; done
kill "$recorder"
