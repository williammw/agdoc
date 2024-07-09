FROM python:3.10.14

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install wget and other dependencies
RUN apt-get update && apt-get install -y wget

# Download and install static FFmpeg
RUN bash /app/bin/download_ffmpeg.sh

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Ensure FFmpeg is in PATH
ENV PATH="/app/bin:${PATH}"

# Run app when the container launches
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]