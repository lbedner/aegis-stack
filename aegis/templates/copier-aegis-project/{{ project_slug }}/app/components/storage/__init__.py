"""Object storage component: an S3 backend for any bucket.

The seam is ``app.core.storage``; this package is the backend that puts
it on a bucket, whether that bucket is AWS, an S3-compatible service, or
the SeaweedFS container the dev compose stack ships.
"""
