# --- Stage 1: Build the Go E2EE binary ---
FROM golang:1.24-alpine AS go-builder

RUN apk add --no-cache git

WORKDIR /app
# Clone the fbchat-v2 repository to compile the E2EE bridge binary
RUN git clone https://github.com/MinhHuyDev/fbchat-v2.git

WORKDIR /app/fbchat-v2/bridge-e2ee
# Clone the mautrix-meta repository dependency
RUN git clone https://github.com/mautrix/meta.git ./meta
# Tidy Go modules and compile
RUN go mod tidy
RUN go build -ldflags="-s -w" -o /app/fbchat-bridge-e2ee .

# --- Stage 2: Final lightweight runner ---
FROM python:3.12-slim

# Install git since we need to clone dependencies (if any) or packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy E2EE bridge binary compiled from Stage 1
COPY --from=go-builder /app/fbchat-bridge-e2ee /app/fbchat-bridge-e2ee

# Copy project source files
COPY src/ ./src/

# Set env variables
ENV PYTHONIOENCODING=utf-8
ENV PORT=8080
ENV FBCHAT_ENABLE_E2EE=1
ENV FBCHAT_E2EE_BIN=/app/fbchat-bridge-e2ee
ENV FBCHAT_V2_USE_PACKAGE=1

EXPOSE 8080

CMD ["python", "src/main.py"]
