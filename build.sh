#!/bin/bash
set -ex

echo "Starting FFmpeg installation process"

# Download and install FFmpeg
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
FFMPEG_DIR="/app/ffmpeg"

echo "Creating directory: $FFMPEG_DIR"
mkdir -p $FFMPEG_DIR

echo "Downloading and extracting FFmpeg"
curl -L $FFMPEG_URL | tar xJ --strip-components=1 -C $FFMPEG_DIR

echo "Listing contents of $FFMPEG_DIR"
ls -la $FFMPEG_DIR

# Add FFmpeg to PATH
echo "Adding FFmpeg to PATH"
export PATH="$FFMPEG_DIR:$PATH"

echo "Current PATH: $PATH"

# Print FFmpeg version to verify installation
echo "Verifying FFmpeg installation"
$FFMPEG_DIR/ffmpeg -version

echo "FFmpeg installation complete"

# Continue with your normal build process
echo "Starting normal build process"
# For example, if you're using pip to install dependencies:
pip install -r requirements.txt

# Any other build steps you need...

echo "Build process complete"