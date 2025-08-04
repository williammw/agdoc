#!/usr/bin/env python3
"""
Monitor when Supabase DNS becomes available
"""
import socket
import time
import os

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

supabase_url = os.getenv("SUPABASE_URL", "https://mzlspxsxifcqotacrhek.supabase.co")
hostname = supabase_url.replace("https://", "").replace("http://", "")

print(f"Monitoring DNS resolution for: {hostname}")
print("Press Ctrl+C to stop\n")

attempt = 1
while True:
    try:
        ip = socket.gethostbyname(hostname)
        print(f"✅ SUCCESS! {hostname} resolved to {ip}")
        print("Your backend should now be able to connect to Supabase!")
        print("Restart your backend application now.")
        break
    except socket.gaierror:
        print(f"Attempt {attempt}: Still waiting for DNS propagation...")
        attempt += 1
        time.sleep(10)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        break