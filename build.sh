#!/usr/bin/env bash
# Install Chrome
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list
apt-get update && apt-get install -y google-chrome-stable

# Print Chrome version
google-chrome --version

# Install dependencies for ChromeDriver
apt-get install -y libglib2.0-0 libnss3 libgconf-2-4 libfontconfig1