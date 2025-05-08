#!/usr/bin/env bash
set -e  # Exit on any error

# Install prerequisites for adding repositories and installing Chrome
apt-get update && apt-get install -y wget gnupg ca-certificates

# Add Google Chrome repository with updated key handling
wget -q -O /tmp/google-chrome-key.asc https://dl.google.com/linux/linux_signing_key.pub
gpg --dearmor /tmp/google-chrome-key.asc
mv /tmp/google-chrome-key.asc.gpg /etc/apt/trusted.gpg.d/
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

# Update package lists and install Google Chrome
apt-get update && apt-get install -y google-chrome-stable

# Install additional dependencies for Chrome and ChromeDriver
apt-get install -y \
    libglib2.0-0 \
    libnss3 \
    libgconf-2-4 \
    libfontconfig1 \
    libxss1 \
    libappindicator3-1 \
    libindicator3-7 \
    libpango-1.0-0 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgtk-3-0

# Print Chrome version to verify installation
google-chrome --version

# Clean up to reduce image size
apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/*
