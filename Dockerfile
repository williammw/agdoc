# Use an official Python runtime as a parent image
FROM python:3.10.14-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
  ffmpeg \
  libpq-dev \
  gcc \
  g++ \
  python3-dev \
  build-essential \
  libssl-dev \
  libffi-dev \
  libxml2-dev \
  libxslt1-dev \
  zlib1g-dev \
  libjpeg-dev \
  libpng-dev \
  libmagic1 \
  libglib2.0-0 \
  libsm6 \
  libxext6 \
  libxrender-dev \
  libgomp1 \
  wget \
  fonts-noto-cjk \
  fonts-noto-color-emoji \
  fontconfig \
  && fc-cache -fv \
  && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Upgrade pip and install wheel
RUN pip install --upgrade pip setuptools wheel

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . /app

# Match what uvicorn actually binds to. EXPOSE is documentation/metadata;
# the real port mapping is configured by the deployment platform. App Platform
# routes external traffic to whatever port the container listens on.
EXPOSE 8000

# Production: no --reload (file watcher would restart mid-render and kill jobs).
# Local dev runs `uvicorn ... --reload` against a venv outside the container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
