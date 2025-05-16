#!/bin/bash

# Check if service account file is provided
if [ -z "$1" ]; then
    echo "Usage: ./set_firebase_env.sh <path-to-service-account.json>"
    exit 1
fi

# Check if file exists
if [ ! -f "$1" ]; then
    echo "Error: Service account file not found at $1"
    exit 1
fi

# Read the JSON file and set it as an environment variable
export FIREBASE_SERVICE_ACCOUNT=$(cat "$1")

# Verify the environment variable was set
if [ -z "$FIREBASE_SERVICE_ACCOUNT" ]; then
    echo "Error: Failed to set FIREBASE_SERVICE_ACCOUNT environment variable"
    exit 1
fi

echo "Firebase service account environment variable has been set successfully"
echo "You can now start your backend server" 