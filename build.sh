#!/bin/bash
set -e

# Download and install FFmpeg
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
FFMPEG_DIR="/app/ffmpeg"

mkdir -p $FFMPEG_DIR
curl -L $FFMPEG_URL | tar xJ --strip-components=1 -C $FFMPEG_DIR

# Add FFmpeg to PATH
export PATH="$FFMPEG_DIR:$PATH"

# Print FFmpeg version to verify installation
$FFMPEG_DIR/ffmpeg -version

# Continue with your normal build process
# For example, if you're using pip to install dependencies:
pip install -r requirements.txt

# Any other build steps you need...