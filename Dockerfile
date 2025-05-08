# Use a slim Python 3.11 base image to keep the image size small
FROM python:3.11-slim

# Set a reliable Debian package source
RUN echo "deb http://deb.debian.org/debian-security bullseye-security main" > /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian bullseye main" >> /etc/apt/sources.list

# Install system dependencies required for Chrome, ChromeDriver, and general utilities
RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates unzip \
    libglib2.0-0 libnss3 libfontconfig1 \
    libxss1 libpango-1.0-0 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

# Add Google Chrome repository and install Chrome
RUN wget -q -O /tmp/google-chrome-key.asc https://dl.google.com/linux/linux_signing_key.pub \
    && gpg --dearmor /tmp/google-chrome-key.asc \
    && mv /tmp/google-chrome-key.asc.gpg /etc/apt/trusted.gpg.d/ \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable

# Install ChromeDriver using the Chrome for Testing API
RUN CHROME_MAJOR_VERSION=$(google-chrome --version | grep -oP '\d+' | head -1) \
    && LATEST_DRIVER_URL=$(wget -qO- "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_${CHROME_MAJOR_VERSION}") \
    && wget -O /tmp/chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/${LATEST_DRIVER_URL}/linux64/chromedriver-linux64.zip" \
    && unzip /tmp/chromedriver.zip -d /tmp/ \
    && mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -rf /tmp/chromedriver.zip /tmp/chromedriver-linux64

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application code
COPY . .

# Expose port 8000 for the FastAPI app
EXPOSE 8000

# Command to run the FastAPI app with Uvicorn
CMD ["uvicorn", "main_FAST:app", "--host", "0.0.0.0", "--port", "8000"]
