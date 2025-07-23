FROM jlesage/baseimage-gui:ubuntu-20.04

ENV HOME=/config

# Name shown in the web UI
ENV APP_NAME="GNOME Files (Nautilus)"

# Install Nautilus, themes & D-Bus helper
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      nautilus \
      dbus-x11 \
      gnome-icon-theme \
      gnome-themes-extra \
      adwaita-icon-theme-full \
      yaru-theme-gtk \
      yaru-theme-icon \
      python3-nautilus \
      xdotool \
     python3-gi \
     gir1.2-nautilus-3.0 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# install our extension into the system folder
RUN mkdir -p /usr/share/nautilus-python/extensions
COPY remote_selection.py /usr/share/nautilus-python/extensions/

ARG PUID=1000
ARG PGID=1000

# 1) Create a group and user with those exact IDs
RUN groupadd --gid ${PGID} user \
 && useradd  --uid  ${PUID} \
              --gid  ${PGID} \
              --create-home \
              --shell     /bin/bash \
              user

# 2) Tell jlesage/baseimage-gui to drop into that same UID/GID
ENV PUID=${PUID}
ENV PGID=${PGID}

# Copy in our launcher
COPY startapp.sh /startapp.sh
RUN chmod +x /startapp.sh

# fire up s6, which will invoke startapp.sh
CMD ["/init"]

# docker build -t ubuntu-files .
