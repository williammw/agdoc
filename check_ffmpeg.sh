#!/bin/bash
echo "Checking FFmpeg installation..."
which ffmpeg
echo "FFmpeg location:"
ls -l $(which ffmpeg)
echo "FFmpeg libraries:"
ldd $(which ffmpeg)
echo "Attempting to run FFmpeg:"
ffmpeg -version
echo "FFmpeg check complete."
echo "PATH:"
echo $PATH
echo "LD_LIBRARY_PATH:"
echo $LD_LIBRARY_PATH