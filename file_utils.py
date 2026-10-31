import os
import uuid
import time
from werkzeug.utils import secure_filename
from flask import current_app

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".csv",
    ".txt",
    ".xlsx",
    ".xls",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}
ALLOWED_ATTACHMENT_MIME_TYPES = {
    "application/pdf",
    "text/csv",
    "text/plain",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}
ALLOWED_TEMPLATE_IMPORT_EXTENSIONS = {".csv", ".xlsx", ".xls"}
ALLOWED_TEMPLATE_IMPORT_MIME_TYPES = {
    "text/csv",
    "text/plain",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
ALLOWED_PDF_EXTENSIONS = {".pdf"}
ALLOWED_PDF_MIME_TYPES = {
    "application/pdf",
}
ALLOWED_COSTING_TEMPLATE_EXTENSIONS = {".xlsx", ".csv"}
ALLOWED_COSTING_TEMPLATE_MIME_TYPES = {
    "text/csv",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


def validate_upload(file_obj, allowed_exts=None, allowed_mimetypes=None, require_image=False):
    if not file_obj or not file_obj.filename:
        raise ValueError("No file uploaded.")

    max_bytes = current_app.config.get("MAX_CONTENT_LENGTH")
    if max_bytes and getattr(file_obj, "content_length", None):
        if file_obj.content_length > max_bytes:
            raise ValueError("File exceeds MAX_CONTENT_LENGTH.")

    ext = os.path.splitext(file_obj.filename)[1].lower()
    if allowed_exts and ext not in allowed_exts:
        raise ValueError(f"File type {ext or '(no extension)'} is not allowed.")

    if allowed_mimetypes and file_obj.mimetype and file_obj.mimetype not in allowed_mimetypes:
        raise ValueError(f"MIME type {file_obj.mimetype} is not allowed.")

    if require_image:
        pos = None
        try:
            pos = file_obj.stream.tell()
            head = file_obj.stream.read(512)
        finally:
            try:
                if pos is not None:
                    file_obj.stream.seek(pos)
            except Exception:
                pass
        if not _looks_like_image(head or b""):
            raise ValueError("Uploaded file is not a recognized image.")


def _looks_like_image(head: bytes) -> bool:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if head[:3] == b"\xff\xd8\xff":
        return True
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return True
    if head.startswith(b"RIFF") and len(head) >= 12 and head[8:12] == b"WEBP":
        return True
    return False


def save_uploaded_file(
    file_obj,
    subdir="",
    allowed_exts=None,
    allowed_mimetypes=None,
    require_image=False,
):
    if not file_obj or file_obj.filename == "":
        return None

    validate_upload(
        file_obj,
        allowed_exts=allowed_exts,
        allowed_mimetypes=allowed_mimetypes,
        require_image=require_image,
    )

    original = secure_filename(file_obj.filename)
    ext = os.path.splitext(original)[1].lower()
    if not original:
        original = f"upload{ext or ''}"
    unique_prefix = uuid.uuid4().hex
    filename = f"{unique_prefix}_{original}"
    folder = current_app.config["UPLOAD_FOLDER"]
    if subdir:
        folder = os.path.join(folder, subdir)
        os.makedirs(folder, exist_ok=True)

    path = os.path.join(folder, filename)
    file_obj.save(path)
    return os.path.relpath(path, current_app.config["UPLOAD_FOLDER"])


def _resolve_upload_root(upload_root: str | None = None) -> str | None:
    if upload_root:
        return upload_root
    try:
        return current_app.config.get("UPLOAD_FOLDER")
    except Exception:
        return None


def _safe_abs_upload_path(rel_path: str, upload_root: str) -> str | None:
    if not rel_path:
        return None
    abs_root = os.path.abspath(upload_root)
    abs_path = os.path.abspath(os.path.join(abs_root, rel_path))
    if os.path.commonpath([abs_root, abs_path]) != abs_root:
        return None
    return abs_path


def delete_upload_file(rel_path: str, upload_root: str | None = None) -> bool:
    root = _resolve_upload_root(upload_root)
    if not root or not rel_path:
        return False
    abs_path = _safe_abs_upload_path(rel_path, root)
    if not abs_path or not os.path.exists(abs_path):
        return False
    try:
        if os.path.isfile(abs_path):
            os.remove(abs_path)
            return True
    except OSError:
        return False
    return False


def delete_job_upload_dir(job_id: int, upload_root: str | None = None) -> int:
    root = _resolve_upload_root(upload_root)
    if not root:
        return 0
    job_dir = os.path.join(root, str(job_id))
    if not os.path.isdir(job_dir):
        return 0
    removed = 0
    for dirpath, _dirnames, filenames in os.walk(job_dir, topdown=False):
        for fname in filenames:
            path = os.path.join(dirpath, fname)
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
        try:
            os.rmdir(dirpath)
        except OSError:
            pass
    return removed


def cleanup_orphaned_files(upload_root: str | None = None, min_age_minutes: int = 60) -> dict:
    root = _resolve_upload_root(upload_root)
    if not root or not os.path.isdir(root):
        return {"removed": 0, "skipped_recent": 0, "checked": 0}

    from models import db, Attachment, IllustrationPage, JobCostingUpload, SurveyItem

    valid_paths = set()
    for rel in db.session.query(Attachment.file_path).filter(Attachment.file_path.isnot(None)).all():
        valid_paths.add(os.path.normpath(rel[0]))
    for rel in db.session.query(Attachment.filename).filter(Attachment.filename.isnot(None)).all():
        valid_paths.add(os.path.normpath(rel[0]))
    for rel in db.session.query(IllustrationPage.image_path).filter(IllustrationPage.image_path.isnot(None)).all():
        valid_paths.add(os.path.normpath(rel[0]))
    for rel in db.session.query(JobCostingUpload.file_path).filter(JobCostingUpload.file_path.isnot(None)).all():
        valid_paths.add(os.path.normpath(rel[0]))
    if hasattr(SurveyItem, "photo_path"):
        for rel in db.session.query(SurveyItem.photo_path).filter(SurveyItem.photo_path.isnot(None)).all():
            valid_paths.add(os.path.normpath(rel[0]))

    cutoff = time.time() - (min_age_minutes * 60)
    removed = 0
    skipped_recent = 0
    checked = 0

    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            abs_path = os.path.join(dirpath, fname)
            checked += 1
            try:
                if os.path.getmtime(abs_path) >= cutoff:
                    skipped_recent += 1
                    continue
            except OSError:
                continue

            rel_path = os.path.normpath(os.path.relpath(abs_path, root))
            if rel_path in valid_paths:
                continue
            try:
                os.remove(abs_path)
                removed += 1
            except OSError:
                pass

    return {"removed": removed, "skipped_recent": skipped_recent, "checked": checked}
