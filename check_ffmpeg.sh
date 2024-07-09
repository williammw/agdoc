#!/bin/bash
echo "Checking FFmpeg installation..."
which ffmpeg
echo "FFmpeg location:"
ls -l $(which ffmpeg)
echo "FFmpeg libraries:"
ldd $(which ffmpeg)
echo "Searching for libpulsecommon:"
find / -name "libpulsecommon*.so" 2>/dev/null
echo "Attempting to run FFmpeg:"
LD_DEBUG=libs ffmpeg -version
echo "FFmpeg check complete."
echo "PATH:"
echo $PATH
echo "LD_LIBRARY_PATH:"
echo $LD_LIBRARY_PATH