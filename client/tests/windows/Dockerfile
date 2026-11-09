# The PC client's end-to-end test machine: the player's Wine image (arm32/wine.Dockerfile: Wine, the virtual screen,
# OpenGL and sound for the game) with a way to see the screen and to click and type on it.
FROM opendmtq-arm32-wine
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends xdotool \
      imagemagick procps >/dev/null && rm -rf /var/lib/apt/lists/*
