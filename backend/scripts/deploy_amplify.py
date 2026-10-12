"""Publish the built frontend to AWS Amplify Hosting (no Git repo needed).

    cd frontend && npm run build          # makes frontend/dist
    cd ../backend
    uv run python scripts/deploy_amplify.py            # create or update the site
    uv run python scripts/deploy_amplify.py --delete   # remove the Amplify app

Re-running updates the same app (its id is kept in backend/.env). The script also adds
the site's URL to COACH_ALLOWED_ORIGINS so the hosted page may call YOUR local API.
The hosted page is public, but it only holds static files: your data stays with the API on
your laptop (and your own AWS account), and the browser asks permission before the page can
reach localhost.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.config import DEFAULT_ORIGINS  # noqa: E402
from coach.envfile import read_env, write_env  # noqa: E402

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
APP_NAME = "career-coach"
BRANCH = "main"


def zip_dist() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(DIST).as_posix())
    return buffer.getvalue()


def allow_origin(origin: str) -> None:
    current = read_env().get("COACH_ALLOWED_ORIGINS", DEFAULT_ORIGINS)
    origins = [o for o in current.split(",") if o]
    if origin not in origins:
        origins.append(origin)
    write_env({"COACH_ALLOWED_ORIGINS": ",".join(origins)})


def disallow_origin(origin: str) -> None:
    current = read_env().get("COACH_ALLOWED_ORIGINS")
    if not current:
        return
    origins = [o for o in current.split(",") if o and o != origin]
    # Back to the defaults? Then drop the line so backend/.env stays minimal.
    write_env({"COACH_ALLOWED_ORIGINS": None if origins == DEFAULT_ORIGINS.split(",") else ",".join(origins)})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION") or read_env().get("AWS_REGION") or "us-east-1")
    parser.add_argument("--delete", action="store_true", help="Delete the Amplify app this script created")
    args = parser.parse_args()

    import boto3

    amplify = boto3.client("amplify", region_name=args.region)
    app_id = read_env().get("COACH_AMPLIFY_APP_ID")

    if args.delete:
        if not app_id:
            print("No COACH_AMPLIFY_APP_ID in backend/.env; nothing to delete.")
            return 0
        try:
            domain = amplify.get_app(appId=app_id)["app"]["defaultDomain"]
        except amplify.exceptions.NotFoundException:
            print(f"Amplify app {app_id} is already gone.")
        else:
            amplify.delete_app(appId=app_id)
            disallow_origin(f"https://{BRANCH}.{domain}")
            print(f"Deleted Amplify app {app_id} and removed https://{BRANCH}.{domain} from the allowed origins.")
        write_env({"COACH_AMPLIFY_APP_ID": None})
        return 0

    if not (DIST / "index.html").exists():
        print(f"{DIST} has no index.html. Run 'npm run build' in the frontend folder first.")
        return 1

    if app_id:
        try:
            app = amplify.get_app(appId=app_id)["app"]
        except amplify.exceptions.NotFoundException:
            app_id = None
    if not app_id:
        app = amplify.create_app(name=APP_NAME, platform="WEB")["app"]
        app_id = app["appId"]
        write_env({"COACH_AMPLIFY_APP_ID": app_id})
        print(f"Created Amplify app {app_id}")
    try:
        amplify.get_branch(appId=app_id, branchName=BRANCH)
    except amplify.exceptions.NotFoundException:
        amplify.create_branch(appId=app_id, branchName=BRANCH)

    deployment = amplify.create_deployment(appId=app_id, branchName=BRANCH)
    payload = zip_dist()
    request = urllib.request.Request(deployment["zipUploadUrl"], data=payload, method="PUT",
                                     headers={"Content-Type": "application/zip"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != 200:
            print(f"Upload failed with HTTP {response.status}")
            return 1
    job_id = deployment["jobId"]
    amplify.start_deployment(appId=app_id, branchName=BRANCH, jobId=job_id)
    print(f"Uploaded {len(payload) / 1024:.0f} KB, deploying (job {job_id}) ...")

    status = "PENDING"
    for _ in range(60):
        status = amplify.get_job(appId=app_id, branchName=BRANCH, jobId=job_id)["job"]["summary"]["status"]
        if status in {"SUCCEED", "FAILED", "CANCELLED"}:
            break
        time.sleep(5)
    if status != "SUCCEED":
        print(f"Deployment ended with status {status}. Check the Amplify console.")
        return 1

    url = f"https://{BRANCH}.{app['defaultDomain']}"
    allow_origin(url)
    print(f"Live: {url}")
    print("Added it to COACH_ALLOWED_ORIGINS in backend/.env. Restart the backend, then open the URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
