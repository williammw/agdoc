#!/bin/bash

# Multivio Background Scheduler Runner
# This script runs the scheduling service and handles logging

set -e

# Configuration
APP_DIR="/app"
LOG_DIR="/var/log"
PYTHON_PATH="/usr/bin/python3"
SCHEDULER_SCRIPT="$APP_DIR/app/services/background_scheduler.py"
LOG_FILE="$LOG_DIR/multivio_scheduler.log"
PID_FILE="/tmp/multivio_scheduler.pid"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - SCHEDULER - $1" | tee -a "$LOG_FILE"
}

# Function to check if scheduler is already running
is_running() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0  # Running
        else
            rm -f "$PID_FILE"  # Remove stale PID file
            return 1  # Not running
        fi
    fi
    return 1  # Not running
}

# Function to run the scheduler
run_scheduler() {
    if is_running; then
        log_message "Scheduler is already running (PID: $(cat $PID_FILE)). Skipping execution."
        return 0
    fi
    
    log_message "Starting background scheduler..."
    
    # Change to app directory
    cd "$APP_DIR"
    
    # Set environment variables
    export PYTHONPATH="$APP_DIR:$PYTHONPATH"
    
    # Run scheduler with timeout (max 10 minutes)
    timeout 600 "$PYTHON_PATH" "$SCHEDULER_SCRIPT" 2>&1 | tee -a "$LOG_FILE" &
    local scheduler_pid=$!
    
    # Store PID
    echo "$scheduler_pid" > "$PID_FILE"
    
    # Wait for completion
    if wait "$scheduler_pid"; then
        log_message "Scheduler completed successfully"
        rm -f "$PID_FILE"
        return 0
    else
        local exit_code=$?
        log_message "Scheduler failed with exit code: $exit_code"
        rm -f "$PID_FILE"
        return $exit_code
    fi
}

# Function to kill running scheduler
kill_scheduler() {
    if is_running; then
        local pid=$(cat "$PID_FILE")
        log_message "Killing running scheduler (PID: $pid)..."
        kill -TERM "$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
        rm -f "$PID_FILE"
        log_message "Scheduler stopped"
    else
        log_message "No scheduler is currently running"
    fi
}

# Function to show scheduler status
show_status() {
    if is_running; then
        local pid=$(cat "$PID_FILE")
        echo "Scheduler is running (PID: $pid)"
        return 0
    else
        echo "Scheduler is not running"
        return 1
    fi
}

# Function to rotate logs
rotate_logs() {
    if [ -f "$LOG_FILE" ]; then
        local file_size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
        # Rotate if log file is larger than 100MB
        if [ "$file_size" -gt 104857600 ]; then
            log_message "Rotating log file (size: $file_size bytes)"
            mv "$LOG_FILE" "${LOG_FILE}.old"
            # Keep only last 5 rotated logs
            find "$LOG_DIR" -name "multivio_scheduler.log.old*" -type f | \
                sort -r | tail -n +6 | xargs -r rm -f
        fi
    fi
}

# Main script logic
case "${1:-run}" in
    "run")
        rotate_logs
        run_scheduler
        ;;
    "stop")
        kill_scheduler
        ;;
    "status")
        show_status
        ;;
    "restart")
        kill_scheduler
        sleep 2
        run_scheduler
        ;;
    "logs")
        if [ -f "$LOG_FILE" ]; then
            tail -f "$LOG_FILE"
        else
            echo "Log file not found: $LOG_FILE"
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 {run|stop|status|restart|logs}"
        echo ""
        echo "Commands:"
        echo "  run     - Run the scheduler (default)"
        echo "  stop    - Stop running scheduler"
        echo "  status  - Show scheduler status"
        echo "  restart - Restart the scheduler"
        echo "  logs    - Follow scheduler logs"
        exit 1
        ;;
esac