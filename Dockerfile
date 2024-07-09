# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install ffmpeg and verify installation
RUN apt-get update && apt-get install -y ffmpeg && ffmpeg -version

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 80 available to the world outside this container
EXPOSE 80

# Define environment variable and ensure FFmpeg is in PATH
ENV PATH="/usr/bin:${PATH}"

# Ensure FFmpeg is executable
RUN chmod +x /usr/bin/ffmpeg

# Run app.py when the container launches
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]