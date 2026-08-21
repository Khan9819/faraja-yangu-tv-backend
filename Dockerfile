# Use the latest official Ubuntu base image
FROM ubuntu:24.04

# Set environment variables to avoid tzdata prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Africa/Nairobi

# Update package list and install necessary packages
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    apt-get install -y build-essential && \
    apt-get install -y libpq-dev && \
    apt-get install -y libssl-dev && \
    apt-get install -y libffi-dev && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y nano nginx tzdata python3.12 python3.12-dev python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Configure the timezone non-interactively
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Create the application directory
RUN mkdir /app

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt /app/

# Install FFmpeg for video processing
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN python3.12 -m pip install --break-system-packages --ignore-installed 'uvicorn[standard]' && \
    python3.12 -m pip install --break-system-packages --ignore-installed -r requirements.txt && \
    python3.12 -m pip install --break-system-packages --ignore-installed psycopg2-binary==2.9.10

# Install Sentry SDK
RUN python3.12 -m pip install --break-system-packages --ignore-installed "sentry-sdk[django]"

# Add xiron to Python path
ENV PYTHONPATH="/app:${PYTHONPATH}"

# Force rebuild: 2026-08-21 scheduled publishing fix
ARG BUILD_DATE
ENV BUILD_DATE=${BUILD_DATE}

# Copy application code (after dependencies are installed)
COPY . /app

# NGINX configuration files
COPY .config/default.conf /etc/nginx/conf.d/default.conf
COPY .config/site.com /etc/nginx/sites-available/default
COPY .config/site.com /etc/nginx/sites-enabled/default

# Copy the start script and ensure it's executable
COPY .entry/start_core_backend.sh /app/start_core_backend.sh
COPY .entry/start_tasks_backend.sh /app/start_tasks_backend.sh
RUN chmod +x /app/start_core_backend.sh
RUN chmod +x /app/start_tasks_backend.sh

# Expose port 80 for the web server
EXPOSE 80

# Set default entry script (can be overridden with environment variable)
ENV ENTRY_SCRIPT="/app/start_core_backend.sh"

# Define the entry point for the container
ENTRYPOINT [ "sh", "-c", "${ENTRY_SCRIPT}" ]
