#!/bin/bash
export PATH="/usr/bin:/usr/local/bin:/app/.apt/usr/bin:/layers/digitalocean_apt/apt/usr/bin:$PATH"
export LD_LIBRARY_PATH="/app/.apt/usr/lib/x86_64-linux-gnu:/app/.apt/usr/lib:/layers/digitalocean_apt/apt/usr/lib/x86_64-linux-gnu:/layers/digitalocean_apt/apt/usr/lib:$LD_LIBRARY_PATH"
echo "PATH has been updated: $PATH"
echo "LD_LIBRARY_PATH has been updated: $LD_LIBRARY_PATH"