#!/bin/bash

# Download static FFmpeg build
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz

# Extract the archive
tar xvf ffmpeg-release-amd64-static.tar.xz

# Move FFmpeg binary to a location in PATH
mkdir -p $HOME/bin
mv ffmpeg-*-amd64-static/ffmpeg $HOME/bin/

# Clean up
rm -rf ffmpeg-*-amd64-static*

# Make FFmpeg executable
chmod +x $HOME/bin/ffmpeg

# Print FFmpeg version
$HOME/bin/ffmpeg -version