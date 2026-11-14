from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from app.core import gate, security
from app.core.db import bucket, get_db, oid
from app.models import Identity
from app.services import campaigns, media

router = APIRouter(tags=["assets"])

MAX_BYTES = 20 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024


@router.post("/assets")
async def upload(file: UploadFile, identity: Identity = Depends(security.current_identity)) -> dict:
    """Upload an audio, image or video ad for review. Returns the id to send with the chat message or the check."""
    data = await file.read()
    try:
        kind = media.kind_of(file.content_type or "")
    except media.UnsupportedMedia as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    if len(data) > (MAX_VIDEO_BYTES if kind == "video" else MAX_BYTES):
        raise HTTPException(status_code=413, detail="File is larger than 50 MB" if kind == "video" else "File is larger than 20 MB")
    run_id = f"upload-{uuid.uuid4()}"

    def save() -> str:
        return str(bucket().upload_from_stream(file.filename or "upload", io.BytesIO(data), metadata={"mime": file.content_type, "team": identity.team, "uploaded_by": identity.user_id}))

    file_id = gate.guarded(
        identity, "compliance.check", {"step": "upload", "type": kind, "bytes": len(data), "filename": file.filename}, run_id, save,
        summarize=lambda f: {"status": "ok", "summary": f"Stored an uploaded {kind} file", "ref": {"collection": "fs.files", "id": f}},
    )
    return {"file_id": file_id, "type": kind}


@router.get("/assets/{file_id}")
def download(file_id: str, identity: Identity = Depends(security.current_identity)) -> Response:
    """Serve a file to someone allowed to see it: its uploader, or anyone who may see an ad that uses it."""
    db = get_db()
    info = db["fs.files"].find_one({"_id": oid(file_id)}, {"metadata": 1})
    if not info:
        raise HTTPException(status_code=404, detail="No such file")
    meta = info.get("metadata") or {}
    used_by_visible_ad = db.campaigns.count_documents(
        {"team": identity.team, "status": {"$in": campaigns.visible_statuses(identity)}, "$or": [{"assets.file_id": file_id}, {"history.assets.file_id": file_id}, {"compliance.annotated_url": f"/assets/{file_id}"}]}, limit=1
    )
    if not used_by_visible_ad and meta.get("uploaded_by") != identity.user_id:
        raise HTTPException(status_code=404, detail="No such file")
    data, mime = media.open_file(file_id)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=300"})
