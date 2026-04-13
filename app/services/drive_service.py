import re
from urllib.parse import parse_qs, urlparse


class DriveLinkError(ValueError):
    pass


def extract_drive_file_id(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        raise DriveLinkError("Ban can nhap link Google Drive hoac file id.")

    if re.fullmatch(r"[-\w]{20,}", value):
        return value

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise DriveLinkError("Link Google Drive khong hop le.")

    query = parse_qs(parsed.query)
    if "id" in query and query["id"]:
        return query["id"][0]

    match = re.search(r"/d/([-\w]{20,})", parsed.path)
    if match:
        return match.group(1)

    match = re.search(r"/file/d/([-\w]{20,})", parsed.path)
    if match:
        return match.group(1)

    raise DriveLinkError("Khong trich xuat duoc file id tu link Google Drive.")


def is_google_document_url(raw_value: str) -> bool:
    value = (raw_value or "").strip()
    if not value:
        return False

    parsed = urlparse(value)
    return parsed.netloc == "docs.google.com" and parsed.path.startswith("/document/d/")


def build_drive_urls(file_id: str, source_url: str = "") -> dict[str, str]:
    if is_google_document_url(source_url):
        return {
            "drive_file_id": file_id,
            "source_kind": "google_doc",
            "drive_view_url": f"https://docs.google.com/document/d/{file_id}/edit",
            "drive_preview_url": f"https://docs.google.com/document/d/{file_id}/preview",
            "drive_download_url": f"https://docs.google.com/document/d/{file_id}/export?format=txt",
            "drive_export_pdf_url": f"https://docs.google.com/document/d/{file_id}/export?format=pdf",
        }

    return {
        "drive_file_id": file_id,
        "source_kind": "drive_file",
        "drive_view_url": f"https://drive.google.com/file/d/{file_id}/view",
        "drive_preview_url": f"https://drive.google.com/file/d/{file_id}/preview",
        "drive_download_url": f"https://drive.google.com/uc?export=download&id={file_id}",
    }
