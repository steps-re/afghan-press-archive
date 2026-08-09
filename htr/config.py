"""Deployment settings, all environment-driven.

Nothing in this repository hardcodes a cloud project, bucket, model endpoint or account. Point
these at your own infrastructure and everything runs unchanged:

    export HTR_PROJECT=my-gcp-project        # required for any model call
    export HTR_BUCKET=gs://my-bucket         # where artefacts are read and written
    export HTR_LOCATION=us-central1          # region for regional endpoints
    export HTR_TUNED_ENDPOINT=projects/…/endpoints/…   # only if you tuned your own reader
    export HTR_GCLOUD_ACCOUNT=you@example.com          # only if you need a non-default identity

Anything unset simply disables the feature that needs it rather than failing late with a
confusing 404 from someone else's project.
"""
import os


def _clean(v: str) -> str:
    return (v or "").strip().rstrip("/")


PROJECT = _clean(os.environ.get("HTR_PROJECT", ""))
LOCATION = _clean(os.environ.get("HTR_LOCATION", "us-central1")) or "us-central1"
BUCKET = _clean(os.environ.get("HTR_BUCKET", ""))
TUNED_ENDPOINT = _clean(os.environ.get("HTR_TUNED_ENDPOINT", ""))
GCLOUD_ACCOUNT = _clean(os.environ.get("HTR_GCLOUD_ACCOUNT", ""))

# Azure is optional and only used for the cross-vendor comparison arm.
AZURE_ENDPOINT = _clean(os.environ.get("HTR_AZURE_ENDPOINT", ""))
AZURE_API_VERSION = os.environ.get("HTR_AZURE_API_VERSION", "2025-04-01-preview")


def require_project() -> str:
    if not PROJECT:
        raise SystemExit(
            "HTR_PROJECT is not set. Export the GCP project that should serve the models:\n"
            "    export HTR_PROJECT=my-gcp-project")
    return PROJECT


def bucket_path(*parts: str) -> str:
    """Join a path under the configured bucket. Fails loudly rather than writing somewhere
    unexpected, which is the failure mode that actually costs you data."""
    if not BUCKET:
        raise SystemExit(
            "HTR_BUCKET is not set. Export the bucket for artefacts:\n"
            "    export HTR_BUCKET=gs://my-bucket")
    base = BUCKET if BUCKET.startswith("gs://") else f"gs://{BUCKET}"
    return "/".join([base.rstrip("/")] + [p.strip("/") for p in parts if p])


def gcloud_args() -> list:
    """Extra gcloud flags for the configured identity and project, or nothing."""
    a = []
    if GCLOUD_ACCOUNT:
        a.append(f"--account={GCLOUD_ACCOUNT}")
    if PROJECT:
        a.append(f"--project={PROJECT}")
    return a
