#!/bin/bash
echo "Checking FFmpeg installation..."
which ffmpeg
echo "FFmpeg location:"
ls -l $(which ffmpeg)
echo "Attempting to run FFmpeg:"
ffmpeg -version
echo "FFmpeg check complete."
echo "PATH:"
echo $PATH