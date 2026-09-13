FROM python:3.11-slim

# Install Tor to bypass IP blocks
RUN apt-get update && apt-get install -y tor && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files
COPY . .

# Run Tor in the background and then start the main scraper
CMD tor & sleep 5 && python main.py
