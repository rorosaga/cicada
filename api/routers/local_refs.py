"""Device-aware local file/folder reference lookup (backlog G27).

Lets the companion app ask "does this local-file reference still resolve on
the machine the API is running on right now?" — used to show
present/moved/missing badges (and offer a relink flow) for entities that
point at files outside the memory graph, especially after ``memory/`` has
been imported onto a different computer.

Security: this endpoint only ever stats a path (existence + file-vs-dir). It
never opens, reads, or returns file contents.
"""

from fastapi import APIRouter, HTTPException, Query

from api.services import local_refs

router = APIRouter()


@router.get("/local-ref")
async def get_local_ref(
    path: str = Query(..., min_length=1, description="Filesystem path recorded on some device"),
    device: str | None = Query(None, description="Device id the path was recorded on"),
):
    """Resolve a local-file reference against the current machine.

    Returns ``{path, device, exists, is_dir, status, resolved_path}``. Never
    reads file contents — only existence/type is reported.
    """
    normalized_path = path.strip()
    if not normalized_path:
        raise HTTPException(status_code=422, detail="path must not be empty")

    normalized_device = device.strip() if device and device.strip() else None
    return local_refs.resolve_local_ref(normalized_path, normalized_device)
