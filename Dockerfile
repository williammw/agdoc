# Use an official Python runtime as a parent image
FROM python:3.10.14-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
  ffmpeg \
  libpq-dev \
  gcc \
  python3-dev \
  && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 80 available to the world outside this container
EXPOSE 80

# Run uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
