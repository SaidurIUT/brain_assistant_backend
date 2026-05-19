from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

GOOGLE_DRIVE = "google_drive"
ONEDRIVE = "onedrive"

SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx", ".md", ".txt", ".csv"}
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
}


class ExternalProviderError(Exception):
    pass


@dataclass(frozen=True)
class ProviderFolder:
    provider_folder_id: str
    name: str
    path: str
    drive_id: str = ""
    parent_id: str = ""


@dataclass(frozen=True)
class ProviderFile:
    provider_file_id: str
    name: str
    mime_type: str
    web_url: str
    modified_at: datetime | None
    size_bytes: int
    checksum: str = ""
    etag: str = ""
    drive_id: str = ""
    parent_folder_id: str = ""

    @property
    def safe_filename(self) -> str:
        extension = Path(self.name).suffix.lower()
        if extension or self.mime_type not in GOOGLE_EXPORTS:
            return Path(self.name).name or self.provider_file_id
        return f"{self.name}{GOOGLE_EXPORTS[self.mime_type][1]}"


class BaseProviderClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def list_folders(self) -> list[ProviderFolder]:
        raise NotImplementedError

    def list_files_for_folder(self, folder: ProviderFolder, recursive: bool) -> list[ProviderFile]:
        raise NotImplementedError

    def download_file(self, file: ProviderFile) -> bytes:
        raise NotImplementedError


class GoogleDriveClient(BaseProviderClient):
    base_url = "https://www.googleapis.com/drive/v3"

    def list_folders(self) -> list[ProviderFolder]:
        params = {
            "q": f"mimeType='{GOOGLE_FOLDER_MIME}' and trashed=false",
            "fields": "nextPageToken,files(id,name,parents)",
            "pageSize": "100",
            "orderBy": "name_natural",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        records = self._paged_files(params)
        by_id = {record["id"]: record for record in records}

        def folder_path(record: dict) -> str:
            names = [record.get("name") or "Untitled folder"]
            parents = record.get("parents") or []
            seen = {record.get("id")}
            while parents:
                parent = by_id.get(parents[0])
                if not parent or parent.get("id") in seen:
                    break
                names.append(parent.get("name") or "Untitled folder")
                seen.add(parent.get("id"))
                parents = parent.get("parents") or []
            return " / ".join(reversed(names))

        return [
            ProviderFolder(
                provider_folder_id=record["id"],
                name=record.get("name") or "Untitled folder",
                path=folder_path(record),
                parent_id=(record.get("parents") or [""])[0],
            )
            for record in records
        ]

    def list_files_for_folder(self, folder: ProviderFolder, recursive: bool) -> list[ProviderFile]:
        files: list[ProviderFile] = []
        self._walk_folder(folder.provider_folder_id, recursive, files)
        return files

    def download_file(self, file: ProviderFile) -> bytes:
        if file.mime_type in GOOGLE_EXPORTS:
            export_mime, _extension = GOOGLE_EXPORTS[file.mime_type]
            url = f"{self.base_url}/files/{quote(file.provider_file_id)}/export"
            params = {"mimeType": export_mime}
        else:
            url = f"{self.base_url}/files/{quote(file.provider_file_id)}"
            params = {"alt": "media"}
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(url, headers=self.headers, params=params)
            _raise_for_provider(response)
            return response.content

    def _walk_folder(self, folder_id: str, recursive: bool, files: list[ProviderFile]) -> None:
        params = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": (
                "nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime,"
                "md5Checksum,size,parents)"
            ),
            "pageSize": "100",
            "orderBy": "folder,name_natural",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        for record in self._paged_files(params):
            if record.get("mimeType") == GOOGLE_FOLDER_MIME:
                if recursive:
                    self._walk_folder(record["id"], recursive, files)
                continue
            files.append(
                ProviderFile(
                    provider_file_id=record["id"],
                    name=record.get("name") or record["id"],
                    mime_type=record.get("mimeType") or "",
                    web_url=record.get("webViewLink") or "",
                    modified_at=_parse_datetime(record.get("modifiedTime")),
                    size_bytes=int(record.get("size") or 0),
                    checksum=record.get("md5Checksum") or "",
                    etag=record.get("modifiedTime") or "",
                    parent_folder_id=(record.get("parents") or [""])[0],
                )
            )

    def _paged_files(self, params: dict[str, str]) -> list[dict]:
        records: list[dict] = []
        page_token = ""
        with httpx.Client(timeout=45) as client:
            while True:
                page_params = dict(params)
                if page_token:
                    page_params["pageToken"] = page_token
                response = client.get(f"{self.base_url}/files", headers=self.headers, params=page_params)
                _raise_for_provider(response)
                payload = response.json()
                records.extend(payload.get("files") or [])
                page_token = payload.get("nextPageToken") or ""
                if not page_token:
                    break
        return records


class OneDriveClient(BaseProviderClient):
    base_url = "https://graph.microsoft.com/v1.0"

    def list_folders(self) -> list[ProviderFolder]:
        folders: list[ProviderFolder] = []
        self._walk_folders("root", "OneDrive", "", folders, depth=0)
        return folders

    def list_files_for_folder(self, folder: ProviderFolder, recursive: bool) -> list[ProviderFile]:
        files: list[ProviderFile] = []
        self._walk_items(folder.provider_folder_id, recursive, files)
        return files

    def download_file(self, file: ProviderFile) -> bytes:
        item_id = quote(file.provider_file_id)
        url = f"{self.base_url}/me/drive/items/{item_id}/content"
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(url, headers=self.headers)
            _raise_for_provider(response)
            return response.content

    def _walk_folders(
        self,
        folder_id: str,
        folder_name: str,
        parent_path: str,
        folders: list[ProviderFolder],
        depth: int,
    ) -> None:
        if depth > 4:
            return
        children = self._children(folder_id)
        for child in children:
            if "folder" not in child:
                continue
            path = f"{parent_path} / {child['name']}" if parent_path else child["name"]
            folders.append(
                ProviderFolder(
                    provider_folder_id=child["id"],
                    drive_id=(child.get("parentReference") or {}).get("driveId") or "",
                    name=child.get("name") or "Untitled folder",
                    path=path,
                    parent_id=(child.get("parentReference") or {}).get("id") or folder_name,
                )
            )
            self._walk_folders(child["id"], child["name"], path, folders, depth + 1)

    def _walk_items(self, folder_id: str, recursive: bool, files: list[ProviderFile]) -> None:
        for child in self._children(folder_id):
            if "folder" in child:
                if recursive:
                    self._walk_items(child["id"], recursive, files)
                continue
            if "file" not in child:
                continue
            parent = child.get("parentReference") or {}
            hashes = (child.get("file") or {}).get("hashes") or {}
            files.append(
                ProviderFile(
                    provider_file_id=child["id"],
                    drive_id=parent.get("driveId") or "",
                    name=child.get("name") or child["id"],
                    mime_type=(child.get("file") or {}).get("mimeType") or "",
                    web_url=child.get("webUrl") or "",
                    modified_at=_parse_datetime(child.get("lastModifiedDateTime")),
                    size_bytes=int(child.get("size") or 0),
                    checksum=hashes.get("quickXorHash") or hashes.get("sha1Hash") or "",
                    etag=child.get("eTag") or child.get("cTag") or "",
                    parent_folder_id=parent.get("id") or folder_id,
                )
            )

    def _children(self, folder_id: str) -> list[dict]:
        if folder_id == "root":
            url = f"{self.base_url}/me/drive/root/children"
        else:
            url = f"{self.base_url}/me/drive/items/{quote(folder_id)}/children"
        params = {
            "$top": "200",
            "$select": "id,name,file,folder,parentReference,eTag,cTag,lastModifiedDateTime,size,webUrl",
        }
        records: list[dict] = []
        with httpx.Client(timeout=45) as client:
            while url:
                response = client.get(url, headers=self.headers, params=params)
                _raise_for_provider(response)
                payload = response.json()
                records.extend(payload.get("value") or [])
                url = payload.get("@odata.nextLink") or ""
                params = {}
        return records


def provider_client(provider: str, access_token: str) -> BaseProviderClient:
    if provider == GOOGLE_DRIVE:
        return GoogleDriveClient(access_token)
    if provider == ONEDRIVE:
        return OneDriveClient(access_token)
    raise ExternalProviderError(f"Unsupported external source provider: {provider}")


def is_supported_file(file: ProviderFile) -> bool:
    if file.mime_type in GOOGLE_EXPORTS:
        return True
    return Path(file.name).suffix.lower() in SUPPORTED_EXTENSIONS


def exported_filename(file: ProviderFile) -> str:
    return file.safe_filename


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _raise_for_provider(response: httpx.Response) -> None:
    if response.is_success:
        return
    detail = ""
    try:
        payload = response.json()
        detail = str(payload.get("error", {}).get("message") or payload.get("error_description") or "")
    except Exception:
        detail = response.text[:300]
    raise ExternalProviderError(detail or f"Provider request failed with {response.status_code}")
