"""List category folders and files; download media to a temp path."""
import io, os, pathlib
from googleapiclient.http import MediaIoBaseDownload
from .gauth import drive
from .util import LOG

ROOT_ID = os.environ.get("DRIVE_ROOT_ID", "")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
TMP = pathlib.Path("tmp")


def content_type_of(name: str):
    ext = pathlib.Path(name).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    return None


def _list(q, fields):
    svc, out, token = drive(), [], None
    while True:
        res = svc.files().list(q=q, fields=fields, pageSize=1000, pageToken=token,
                               supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute()
        out.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            return out


def category_folders() -> dict:
    q = (f"'{ROOT_ID}' in parents and mimeType='application/vnd.google-apps.folder' "
         f"and trashed=false")
    folders = _list(q, "nextPageToken, files(id,name)")
    return {f["name"]: f["id"] for f in folders
            if not f["name"].startswith(("_", "zz-"))}


def files_in(folder_id: str) -> list:
    q = f"'{folder_id}' in parents and trashed=false"
    files = _list(q, "nextPageToken, files(id,name,mimeType,size,md5Checksum,"
                     "videoMediaMetadata,imageMediaMetadata,createdTime)")
    return [f for f in files if not f["name"].startswith("_")
            or f["name"] == "_meta.csv"]


def download_text(file_id: str) -> str:
    return drive().files().get_media(fileId=file_id).execute().decode("utf-8-sig")


def download(file_id: str, filename: str) -> pathlib.Path:
    TMP.mkdir(exist_ok=True)
    dest = TMP / f"{file_id}{pathlib.Path(filename).suffix.lower()}"
    if dest.exists():
        return dest
    req = drive().files().get_media(fileId=file_id, supportsAllDrives=True)
    with io.FileIO(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()
    LOG.info("downloaded %s (%.1f MB)", filename, dest.stat().st_size / 1e6)
    return dest
