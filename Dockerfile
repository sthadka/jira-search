# Multi-stage build with UBI for enterprise security
FROM registry.access.redhat.com/ubi9/python-311:latest as builder

# Switch to root for build operations
USER 0

# Install build dependencies
RUN dnf update -y && \
    dnf install -y \
        gcc \
        gcc-c++ \
        make \
        wget \
        tar \
        gzip \
    && dnf clean all

# Build and install SQLite 3.50.4 for consistent FTS5 ranking
RUN wget --progress=dot:mega https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz && \
    # In production, add checksum verification here
    echo "Add checksum verification in production" && \
    tar xzf sqlite-autoconf-3500400.tar.gz && \
    cd sqlite-autoconf-3500400 && \
    ./configure --prefix=/opt/sqlite \
        --enable-fts5 \
        --enable-rtree \
        --disable-static \
        --enable-shared && \
    make && \
    make install && \
    cd .. && \
    rm -rf sqlite-autoconf-3500400*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Install Python dependencies using uv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable

# Production stage - UBI Minimal for enterprise security with tools
FROM registry.access.redhat.com/ubi9-minimal:latest

# Install minimal runtime dependencies
RUN microdnf update -y && \
    microdnf install -y \
        python3.11 \
        python3.11-libs \
        python3.11-pip \
        glibc \
        libgcc \
        shadow-utils \
    && microdnf clean all

# Copy SQLite from builder stage
COPY --from=builder /opt/sqlite /usr/local
RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/sqlite.conf && ldconfig

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create app user for security
RUN groupadd -g 1000 appuser && \
    useradd -r -u 1000 -g appuser -s /sbin/nologin -c "App User" appuser

# Set working directory
WORKDIR /app

# Copy application with proper ownership
COPY --from=builder --chown=appuser:appuser /opt/app-root/src/pyproject.toml .

# Create data directory with proper permissions
RUN mkdir -p /app/data && \
    chown -R appuser:appuser /app && \
    chmod 755 /app && \
    chmod 755 /app/data


# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/status')" || exit 1

# Security and metadata labels
LABEL name="jira-search-ubi" \
      version="1.0" \
      description="Jira Search Application on UBI Minimal" \
      security.base-image="ubi9-minimal" \
      security.non-root="true" \
      security.enterprise="true" \
      security.updates="2025-01-08"

# Default command with security settings
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "4", \
     "--timeout", "120", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--preload", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "jira_search.wsgi:application"]