"""The 90-second doorstep: put a file on R2, hand out its public URL, delete it."""
import mimetypes, os, pathlib
import boto3
from botocore.config import Config
from .util import LOG, env

BUCKET = os.environ.get("R2_BUCKET", "content-staging")
PUBLIC = os.environ.get("R2_PUBLIC_BASE", "").rstrip("/")


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=env("R2_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4", region_name="auto"),
    )


def put(local: pathlib.Path, key: str) -> str:
    """Upload and return a public https URL. Key must be ASCII-only."""
    ctype = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
    _client().upload_file(str(local), BUCKET, key,
                          ExtraArgs={"ContentType": ctype})
    url = f"{PUBLIC}/{key}"
    LOG.info("staged %s -> %s", local.name, url)
    return url


def delete(key: str):
    try:
        _client().delete_object(Bucket=BUCKET, Key=key)
        LOG.info("unstaged %s", key)
    except Exception as e:                       # never fail a run over cleanup
        LOG.warning("could not delete staged object %s: %s", key, e)


def key_for(job_id: int, content_id: str, suffix: str) -> str:
    """ASCII-safe key. Never use the original filename: Meta rejects non-ASCII URLs."""
    return f"stg/{job_id}-{content_id[:16]}{suffix.lower()}"
