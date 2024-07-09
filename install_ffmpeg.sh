#!/bin/bash

# Download static FFmpeg build
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz

# Extract the archive
tar xvf ffmpeg-release-amd64-static.tar.xz

# Move FFmpeg binary to a location in PATH
mkdir -p /app/bin
mv ffmpeg-*-amd64-static/ffmpeg /app/bin/

# Clean up
rm -rf ffmpeg-*-amd64-static*

# Make FFmpeg executable
chmod +x /app/bin/ffmpeg

# Print FFmpeg version
/app/bin/ffmpeg -version