# Multi-stage build for optimized production image
FROM python:3.13-slim as builder

# Install build dependencies for Python packages and SQLite
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    wget \
    make \
    && rm -rf /var/lib/apt/lists/*

# Build and install SQLite 3.50.4 for consistent FTS5 ranking
RUN wget https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz && \
    tar xzf sqlite-autoconf-3500400.tar.gz && \
    cd sqlite-autoconf-3500400 && \
    ./configure --prefix=/opt/sqlite && \
    make && \
    make install && \
    cd .. && \
    rm -rf sqlite-autoconf-3500400*

# Create virtual environment and install Python dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Production stage
FROM python:3.13-slim

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy SQLite from builder stage
COPY --from=builder /opt/sqlite /usr/local
RUN ldconfig

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create app user for security
RUN groupadd -g 1000 appuser && \
    useradd -r -u 1000 -g appuser appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY src/ ./src/
COPY setup.py .
COPY requirements.txt .

# Install the application
RUN pip install -e .

# Create data directory for SQLite database
RUN mkdir -p /app/data && chown appuser:appuser /app/data

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/api/status || exit 1

# Default command - use Gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "jira_search.wsgi:application"]