#!/bin/bash
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
FFMPEG_DIR="/tmp/ffmpeg"

mkdir -p $FFMPEG_DIR
wget -qO- $FFMPEG_URL | tar xJ -C $FFMPEG_DIR --strip-components=1
mv $FFMPEG_DIR/ffmpeg /app/bin/ffmpeg
chmod +x /app/bin/ffmpeg