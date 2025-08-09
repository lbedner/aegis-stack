# Health Monitoring

{{ cookiecutter.project_name }} includes comprehensive health monitoring capabilities through both API endpoints and CLI commands.

## Health Check Endpoints

### Basic Health Check
- **URL**: `GET /health/`
- **Purpose**: Quick health status check
- **Response Time**: < 100ms

### Detailed Health Check  
- **URL**: `GET /health/detailed`
- **Purpose**: Comprehensive system health with metrics
- **Response Time**: < 500ms

## CLI Health Commands

{{ cookiecutter.project_name }} provides a built-in CLI for health monitoring:

### Basic Health Check
```bash
{{ cookiecutter.project_slug }} health check
```

**Output:**
```
✅ {{ cookiecutter.project_name }} - System Status: HEALTHY

🖥️  System Health:
   • CPU Usage: 15.2%
   • Memory Usage: 45.8%  
   • Disk Usage: 32.1%
   • Response Time: 2.1ms{% if cookiecutter.include_scheduler == "yes" %}

⏰ Scheduler Health:
   • Status: HEALTHY
   • Active Jobs: 2
   • Next Run: 2024-01-01 02:00:00
   • Response Time: 1.5ms{% endif %}

🔍 Overall Health: 98.5%
```

### Detailed Health Check
```bash
{{ cookiecutter.project_slug }} health check --detailed
```

Shows comprehensive system information including:
- Component-level health status
- System resource utilization
- Response time metrics
- Uptime information

### JSON Output
```bash
{{ cookiecutter.project_slug }} health check --json
```

Returns structured JSON for integration with monitoring systems:

```json
{
  "healthy": true,
  "status": "healthy",
  "components": {
    "system": {
      "status": "healthy",
      "cpu_percent": 15.2,
      "memory_percent": 45.8,
      "disk_percent": 32.1,
      "response_time_ms": 2.1
    }{% if cookiecutter.include_scheduler == "yes" %},
    "scheduler": {
      "status": "healthy", 
      "active_jobs": 2,
      "next_run": "2024-01-01T02:00:00Z",
      "response_time_ms": 1.5
    }{% endif %}
  },
  "timestamp": "2024-01-01T00:00:00Z",
  "uptime_seconds": 3600,
  "health_percentage": 98.5
}
```

### Quick Health Check
```bash
{{ cookiecutter.project_slug }} health quick
```

Returns simple healthy/unhealthy status for use in scripts.

## Using Health Checks in Development

### Make Commands
Convenient make targets are available:

```bash
make health         # Basic health check
make health-detailed # Detailed health information  
make health-json    # JSON health output
make health-quick   # Quick healthy/unhealthy check
```

### Fallback Method
If CLI installation fails, use the fallback method:

```bash
make health-fallback  # Uses uv run directly
```

## Health Check Components

### System Health
Monitors core system resources:

- **CPU Usage**: Current CPU utilization percentage
- **Memory Usage**: RAM utilization percentage  
- **Disk Usage**: Disk space utilization percentage
- **Response Time**: Health check response time{% if cookiecutter.include_scheduler == "yes" %}

### Scheduler Health  
Monitors the background task scheduler:

- **Scheduler Status**: Running/stopped status
- **Active Jobs**: Number of currently scheduled jobs
- **Next Run**: When the next job will execute
- **Job History**: Recent job execution status{% endif %}

## Integration with Monitoring Systems

### Prometheus Metrics
To add Prometheus metrics:

```python
# app/components/backend/middleware/prometheus.py
from prometheus_client import Counter, Histogram, generate_latest
from fastapi import Request, Response

REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration')

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path).inc()
    REQUEST_DURATION.observe(time.time() - start_time)
    
    return response

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

### External Health Checks
The health endpoints can be monitored by external systems:

- **Uptime monitoring**: Ping `/health/` endpoint
- **Performance monitoring**: Track `/health/detailed` response times
- **Alerting**: Monitor health percentage thresholds

### Docker Health Checks
The Docker container includes built-in health checks:

```dockerfile
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

## Troubleshooting Health Issues

### Common Issues

**Health check timeouts:**
- Check if application is running on expected port
- Verify no firewall blocking connections
- Check application logs for startup errors

**High resource usage:**
- Monitor CPU/memory usage over time
- Check for memory leaks in long-running processes
- Review recent code changes{% if cookiecutter.include_scheduler == "yes" %}

**Scheduler issues:**
- Check scheduler logs for job failures
- Verify scheduled job configurations
- Monitor job execution times{% endif %}

### Debug Commands
```bash
# Check if service is running
curl http://localhost:8000/health/

# Check application logs  
docker compose logs -f

# Monitor resource usage
docker stats

# Test CLI connectivity
{{ cookiecutter.project_slug }} health check --debug
```

## Health Check Best Practices

1. **Regular Monitoring**: Set up automated health checks every 30-60 seconds
2. **Alerting Thresholds**: Alert when health percentage drops below 95%
3. **Response Time Monitoring**: Alert on health check response times > 1 second
4. **Component-Level Monitoring**: Monitor individual components, not just overall health
5. **Historical Tracking**: Store health metrics for trend analysis

## Customizing Health Checks

To add custom health checks, extend the system service:

```python
# app/services/system_service.py
async def check_database_health() -> ComponentHealth:
    """Check database connectivity."""
    try:
        # Perform database ping
        start_time = datetime.utcnow()
        # ... database check logic ...
        end_time = datetime.utcnow()
        
        return ComponentHealth(
            status="healthy",
            details={
                "connection_pool": "active",
                "query_response_ms": (end_time - start_time).total_seconds() * 1000
            },
            response_time_ms=(end_time - start_time).total_seconds() * 1000
        )
    except Exception as e:
        return ComponentHealth(
            status="unhealthy", 
            details={"error": str(e)},
            response_time_ms=0
        )
```

Then register it in the health check system to have it included in all health reports.