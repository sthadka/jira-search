# Security Documentation

This document outlines the security measures implemented in the Jira Search container image.

## Container Security Hardening

### Base Image Security
- **Security Updates**: Both build and production stages run `apt-get upgrade -y` to install latest security patches
- **Minimal Attack Surface**: Production image only includes essential runtime dependencies
- **Package Cleanup**: Remove package cache, run `autoremove`, and clean up after installations

### User Security
- **Non-root Execution**: Application runs as non-privileged user `appuser` (UID 1000)
- **Shell Restriction**: App user has `/sbin/nologin` shell to prevent interactive access
- **File Permissions**: Explicit ownership and permissions set on application directories

### Dependency Security
Python dependencies updated to latest secure versions:
- `requests`: 2.31.0 → 2.32.0 (security patches)
- `flask`: 2.3.0 → 3.1.0 (multiple CVE fixes)
- `gunicorn`: 21.2.0 → 23.0.0 (security improvements)
- `black`: 23.0.0 → 25.1.0 (latest stable)
- `pytest`: 7.4.0 → 8.4.0 (latest stable)

### Build Security
- **CA Certificates**: Include `ca-certificates` for secure package verification
- **Source Verification**: Added structure for checksum verification (placeholder implemented)
- **Build Dependencies**: Install `gnupg` for package signature verification
- **Multi-stage Build**: Separate build and runtime environments

### Runtime Security
- **Application Isolation**: Runs in `/app` directory with proper ownership
- **Gunicorn Security**: Added security-focused configuration:
  - `--max-requests 1000`: Restart workers periodically
  - `--max-requests-jitter 100`: Add randomness to restarts
  - `--preload`: Load application before forking workers

### File System Security
- **dockerignore**: Comprehensive exclusion of sensitive files:
  - Development tools and configuration
  - Git history and IDE files
  - Local secrets and credentials
  - Test data and temporary files

## Security Monitoring

### Labels and Metadata
Container includes security-relevant labels:
- `security.non-root=true`: Confirms non-root execution
- `security.updates=2025-01-08`: Tracks last security update

### Health Checks
- Built-in health check endpoint at `/api/status`
- 30-second intervals with 10-second timeout
- 3 retries before marking unhealthy

## Vulnerability Management

### Regular Updates
1. **Base Image**: Keep Python 3.13-slim updated
2. **Dependencies**: Monitor for security advisories
3. **System Packages**: Regular `apt-get upgrade` in builds

### Scanning Recommendations
- Run container vulnerability scans on each build
- Monitor dependencies with tools like `safety` or `bandit`
- Use static analysis on application code

## Security Best Practices

### Configuration
- Never include secrets in the container image
- Use environment variables or mounted secrets
- Configure rate limiting in production

### Network Security
- Run behind reverse proxy (nginx, traefik)
- Use TLS termination at proxy level
- Implement network policies in Kubernetes

### Access Control
- Use least-privilege service accounts
- Implement proper RBAC in Kubernetes
- Monitor access logs and patterns

## Compliance

This security configuration addresses common vulnerabilities:
- **CVE Mitigation**: Updated dependencies address known CVEs
- **Container Security**: Follows CIS Benchmark recommendations
- **OWASP**: Addresses container security top 10 risks

## Security Reporting

If you discover a security vulnerability, please:
1. Do not create a public issue
2. Contact the maintainers privately
3. Provide detailed reproduction steps
4. Allow time for responsible disclosure

## Verification

To verify security measures in the running container:

```bash
# Check running user
podman exec <container> whoami

# Verify file permissions
podman exec <container> ls -la /app

# Check package versions
podman exec <container> pip list

# Verify no development tools
podman exec <container> which git || echo "Not found (good)"
```

Last updated: 2025-01-08