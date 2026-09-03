# Configuration

Which backend a project uses, and what the S3 one needs to reach its bucket.

## Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| `STORAGE_BACKEND` | `s3` with this component, `filesystem` without it | Which backend `get_storage()` builds |
| `STORAGE_ROOT` | `storage_data` | Where the filesystem backend keeps objects |
| `S3_ENDPOINT_URL` | `http://seaweedfs:8333` in compose | The endpoint to talk to; empty for AWS |
| `S3_BUCKET` | the project slug | Created on first use if missing |
| `S3_ACCESS_KEY` | placeholder for SeaweedFS | Real credentials in production |
| `S3_SECRET_KEY` | placeholder for SeaweedFS | Real credentials in production |
| `S3_REGION` | `us-east-1` | |
| `S3_PATH_STYLE` | `true` | Path-style addressing; most self-hosted stores need it |

Without the component, `STORAGE_BACKEND=filesystem` and the S3 settings are ignored. That is a working default, not a placeholder: content-addressed keys mean a project can run on disk for as long as it likes.

## Pointing at a Real Store

=== "AWS S3"

    ```bash
    S3_ENDPOINT_URL=            # empty: boto3 resolves the AWS endpoint
    S3_BUCKET=my-app-documents
    S3_ACCESS_KEY=AKIA...
    S3_SECRET_KEY=...
    S3_REGION=us-east-1
    S3_PATH_STYLE=false         # AWS prefers virtual-host addressing
    ```

=== "SeaweedFS (the dev container)"

    ```bash
    S3_ENDPOINT_URL=http://seaweedfs:8333
    S3_BUCKET=my-app
    S3_ACCESS_KEY=aegis
    S3_SECRET_KEY=aegis-secret
    S3_PATH_STYLE=true
    ```

=== "Garage, MinIO, or another self-hosted store"

    ```bash
    S3_ENDPOINT_URL=https://s3.example.com
    S3_BUCKET=my-app
    S3_ACCESS_KEY=...
    S3_SECRET_KEY=...
    S3_REGION=garage            # whatever the store calls its region
    S3_PATH_STYLE=true
    ```

!!! warning "Path style is the setting people get wrong"
    Virtual-host addressing puts the bucket in the hostname (`my-app.s3.example.com`), which self-hosted stores usually cannot serve and TLS certificates usually do not cover. Leave `S3_PATH_STYLE=true` for anything that is not AWS.

## The Bucket

The backend creates the bucket on first use if it is missing, so a fresh dev stack needs no setup step. In production that means the credentials need `CreateBucket`, or the bucket should exist already. The health check reports which state it found.

## The Dev Container

```yaml
seaweedfs:
  image: chrislusf/seaweedfs:4.45
  command: server -s3 -dir=/data -ip=seaweedfs -ip.bind=0.0.0.0 -master.volumeSizeLimitMB=1024
```

Only the S3 port is published, and the data lives in a named volume that survives `make restart` and is removed by `make clean`. It is a dev dependency: production points the same settings at a real store and does not run this service.

## Health

The dashboard's storage card reports the backend in use, the endpoint, the bucket, whether it is reachable, and object counts when the documents service is present. A store that cannot be reached shows as unhealthy there rather than failing at the moment someone uploads a file.

## Next Steps

| Topic | Description |
|-------|-------------|
| **[Examples](examples.md)** | Using storage from a service, and moving an existing project |
| **[Getting Started](index.md)** | The protocol and content-addressed keys |

---

**Related:**

- **[Documents Service](../../services/documents/index.md)** - The largest consumer
