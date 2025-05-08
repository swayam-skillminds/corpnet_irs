# Use a slim Python 3.11 base image to keep the image size small
FROM python:3.11-slim

# Install system dependencies required for Chrome, ChromeDriver, and general utilities
RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates unzip \
    libglib2.0-0 libnss3 libgconf-2-4 libfontconfig1 \
    libxss1 libappindicator3-1 libindicator3-7 \
    libpango-1.0-0 libatk1.0-0 libatk-bridge2.0-0 libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

# Add Google Chrome repository and install Chrome
RUN wget -q -O /tmp/google-chrome-key.asc https://dl.google.com/linux/linux_signing_key.pub \
    && gpg --dearmor /tmp/google-chrome-key.asc \
    && mv /tmp/google-chrome-key.asc.gpg /etc/apt/trusted.gpg.d/ \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable

# Install ChromeDriver matching the installed Chrome version
RUN CHROME_VERSION=$(google-chrome --version | grep -oP '\d+\.\d+\.\d+') \
    && wget -O /tmp/chromedriver.zip https://chromedriver.storage.googleapis.com/${CHROME_VERSION}/chromedriver_linux64.zip \
    && unzip /tmp/chromedriver.zip chromedriver -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/chromedriver \
    && rm /tmp/chromedriver.zip

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
