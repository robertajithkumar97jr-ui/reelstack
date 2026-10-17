"""Student file upload - Flask backend (Elastic Beanstalk entry point: application:application).

Storage layout in the S3 bucket:
  uploads/<uuid>.<ext>        the uploaded file
  submissions/<uuid>.json     the submission record (name, student ID, course, file info, time)
"""
import json
import os
import re
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, Response, abort, jsonify, redirect, render_template,
                   request, send_from_directory)
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
S3_BUCKET = os.environ.get("S3_BUCKET", "").strip()
REQUIRE_S3 = os.environ.get("REQUIRE_S3", "").lower() in ("1", "true", "yes")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
                      "txt", "csv", "png", "jpg", "jpeg", "zip"}
STUDENT_ID_RE = re.compile(r"^[A-Za-z0-9_\-/]{3,30}$")
SUB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


# ---------- storage backends ----------
class S3Store:
    """Files and submission records both live in S3 (uses the EB instance role)."""

    def __init__(self, bucket, client=None):
        if client is None:
            import boto3
            client = boto3.client("s3")
        self.bucket = bucket
        self.s3 = client

    def save_file(self, stream, stored_name):
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        self.s3.upload_fileobj(stream, self.bucket, f"uploads/{stored_name}",
                               ExtraArgs={"ServerSideEncryption": "AES256"})
        return size

    def put_meta(self, meta):
        self.s3.put_object(Bucket=self.bucket, Key=f"submissions/{meta['id']}.json",
                           Body=json.dumps(meta).encode(), ContentType="application/json",
                           ServerSideEncryption="AES256")

    def get_meta(self, sub_id):
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=f"submissions/{sub_id}.json")
        except self.s3.exceptions.NoSuchKey:
            return None
        return json.loads(obj["Body"].read())

    def list_meta(self):
        keys = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix="submissions/"):
            keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".json")]

        def load(key):
            return json.loads(self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read())
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(load, keys))

    def delete(self, meta):
        self.s3.delete_object(Bucket=self.bucket, Key=f"uploads/{meta['stored_name']}")
        self.s3.delete_object(Bucket=self.bucket, Key=f"submissions/{meta['id']}.json")

    def download(self, meta):
        url = self.s3.generate_presigned_url(
            "get_object", ExpiresIn=300,
            Params={"Bucket": self.bucket, "Key": f"uploads/{meta['stored_name']}",
                    "ResponseContentDisposition":
                    f'attachment; filename="{meta["original_name"]}"'})
        return redirect(url)


class LocalStore:
    """Local-disk fallback for development only."""

    def __init__(self, root):
        self.uploads = os.path.join(root, "uploads")
        self.records = os.path.join(root, "submissions")
        os.makedirs(self.uploads, exist_ok=True)
        os.makedirs(self.records, exist_ok=True)

    def save_file(self, stream, stored_name):
        path = os.path.join(self.uploads, stored_name)
        with open(path, "wb") as out:
            out.write(stream.read())
        return os.path.getsize(path)

    def put_meta(self, meta):
        with open(os.path.join(self.records, f"{meta['id']}.json"), "w") as out:
            json.dump(meta, out)

    def get_meta(self, sub_id):
        try:
            with open(os.path.join(self.records, f"{sub_id}.json")) as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def list_meta(self):
        items = []
        for name in os.listdir(self.records):
            if name.endswith(".json"):
                with open(os.path.join(self.records, name)) as f:
                    items.append(json.load(f))
        return items

    def delete(self, meta):
        for path in (os.path.join(self.uploads, meta["stored_name"]),
                     os.path.join(self.records, f"{meta['id']}.json")):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def download(self, meta):
        return send_from_directory(self.uploads, meta["stored_name"], as_attachment=True,
                                   download_name=meta["original_name"])


if REQUIRE_S3 and not S3_BUCKET:
    raise RuntimeError("S3_BUCKET environment variable is required but not set.")
store = S3Store(S3_BUCKET) if S3_BUCKET else LocalStore(DATA_DIR)

application = Flask(__name__)
app = application  # alias for `flask run`
application.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


# ---------- auth for admin routes ----------
def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not ADMIN_PASSWORD:
            abort(503, "Admin is disabled. Set the ADMIN_PASSWORD environment variable.")
        auth = request.authorization
        ok = (auth and auth.type == "basic"
              and secrets.compare_digest(auth.username or "", ADMIN_USERNAME)
              and secrets.compare_digest(auth.password or "", ADMIN_PASSWORD))
        if not ok:
            return Response("Login required", 401,
                            {"WWW-Authenticate": 'Basic realm="Student uploads admin"'})
        return view(*args, **kwargs)
    return wrapper


# ---------- pages ----------
@application.get("/")
def index():
    return render_template("index.html", max_mb=MAX_UPLOAD_MB,
                           extensions=sorted(ALLOWED_EXTENSIONS))


@application.get("/admin")
@require_admin
def admin():
    return render_template("admin.html")


@application.get("/health")
def health():
    return jsonify(status="ok", storage="s3" if S3_BUCKET else "local")


# ---------- student upload API ----------
@application.post("/api/upload")
def upload():
    name = request.form.get("student_name", "").strip()
    student_id = request.form.get("student_id", "").strip()
    course = request.form.get("course", "").strip()[:80]
    files = [f for f in request.files.getlist("files") if f and f.filename]

    errors = []
    if len(name) < 2 or len(name) > 80:
        errors.append("Enter your full name (2-80 characters).")
    if not STUDENT_ID_RE.match(student_id):
        errors.append("Student ID must be 3-30 characters: letters, numbers, - _ /")
    if not files:
        errors.append("Choose at least one file.")
    for f in files:
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"'{f.filename}' is not an allowed file type.")
    if errors:
        return jsonify(ok=False, errors=errors), 400

    saved = []
    try:
        for f in files:
            original = secure_filename(f.filename) or "file"
            ext = original.rsplit(".", 1)[-1].lower()
            sub_id = uuid.uuid4().hex
            stored = f"{sub_id}.{ext}"
            size = store.save_file(f.stream, stored)
            store.put_meta({
                "id": sub_id, "student_name": name, "student_id": student_id,
                "course": course, "original_name": original, "stored_name": stored,
                "size_bytes": size,
                "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            saved.append(original)
    except Exception:
        application.logger.exception("Upload failed")
        return jsonify(ok=False, errors=["Could not save your files. Please try again."]), 500
    return jsonify(ok=True, saved=saved)


# ---------- admin API ----------
@application.get("/api/admin/files")
@require_admin
def list_files():
    q = request.args.get("q", "").strip().lower()
    items = store.list_meta()
    if q:
        items = [i for i in items
                 if q in i["student_name"].lower() or q in i["student_id"].lower()
                 or q in (i.get("course") or "").lower()]
    items.sort(key=lambda i: i["uploaded_at"], reverse=True)
    return jsonify(items)


def _find(sub_id):
    if not SUB_ID_RE.match(sub_id):
        abort(404)
    meta = store.get_meta(sub_id)
    if not meta:
        abort(404)
    return meta


@application.get("/admin/download/<sub_id>")
@require_admin
def download(sub_id):
    return store.download(_find(sub_id))


@application.delete("/api/admin/files/<sub_id>")
@require_admin
def delete_file(sub_id):
    store.delete(_find(sub_id))
    return jsonify(ok=True)


# ---------- errors ----------
@application.errorhandler(413)
def too_large(_e):
    return jsonify(ok=False, errors=[f"Total upload is larger than {MAX_UPLOAD_MB} MB."]), 413


if __name__ == "__main__":
    application.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
