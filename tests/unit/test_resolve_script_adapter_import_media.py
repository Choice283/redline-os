from pathlib import Path

import pytest

from redline_core.resolve.adapter import ResolveScriptAdapter
from redline_core.resolve.exceptions import MediaImportError, ProjectNotFoundError, ResolveConnectionError


class FakeFolder:
    def __init__(self, name: str, subfolders: list["FakeFolder"] | None = None):
        self.name = name
        self.subfolders = subfolders or []

    def GetName(self):
        return self.name

    def GetSubFolderList(self):
        return self.subfolders


class FakeMediaPool:
    def __init__(self, root_folder: FakeFolder, add_result=None, set_current_result=True):
        self.root_folder = root_folder
        self.add_result = add_result
        self.set_current_result = set_current_result
        self.add_calls = []
        self.current_folder = None

    def GetRootFolder(self):
        return self.root_folder

    def AddSubFolder(self, root_folder, bin_name: str):
        self.add_calls.append((root_folder, bin_name))
        if self.add_result is False:
            return False
        if self.add_result is not None:
            return self.add_result
        folder = FakeFolder(bin_name)
        root_folder.subfolders.append(folder)
        return folder

    def SetCurrentFolder(self, folder):
        self.current_folder = folder
        return self.set_current_result


class FakeProject:
    def __init__(self, media_pool: FakeMediaPool):
        self.media_pool = media_pool

    def GetMediaPool(self):
        return self.media_pool


class FakeProjectManager:
    def __init__(self, project=None):
        self.project = project
        self.load_calls = []

    def LoadProject(self, project_name: str):
        self.load_calls.append(project_name)
        return self.project


class FakeMediaStorage:
    def __init__(self, result):
        self.result = result
        self.import_calls = []

    def AddItemListToMediaPool(self, paths: list[str]):
        self.import_calls.append(paths)
        return self.result


class FakeResolve:
    def __init__(self, media_storage: FakeMediaStorage):
        self.media_storage = media_storage
        self.media_storage_calls = 0

    def GetMediaStorage(self):
        self.media_storage_calls += 1
        return self.media_storage


DEFAULT_IMPORT_RESULT = object()


class FakeMediaItem:
    def __init__(self, media_id=None, unique_id=None, has_media_id=True, has_unique_id=True):
        self.media_id = media_id
        self.unique_id = unique_id
        self.has_media_id = has_media_id
        self.has_unique_id = has_unique_id

    def GetMediaId(self):
        if not self.has_media_id:
            raise AttributeError("GetMediaId unavailable")
        return self.media_id

    def GetUniqueId(self):
        if not self.has_unique_id:
            raise AttributeError("GetUniqueId unavailable")
        return self.unique_id


def media_file(tmp_path: Path, name: str = "clip.mov") -> Path:
    path = tmp_path / name
    path.write_bytes(b"media")
    return path


def connected_adapter(project=None, import_result=DEFAULT_IMPORT_RESULT, media_pool=None):
    if media_pool is None:
        media_pool = FakeMediaPool(FakeFolder("root"))
    if project is None:
        project = FakeProject(media_pool)
    if import_result is DEFAULT_IMPORT_RESULT:
        import_result = [FakeMediaItem("clip-1")]
    storage = FakeMediaStorage(import_result)
    adapter = ResolveScriptAdapter()
    adapter._project_manager = FakeProjectManager(project)
    adapter._resolve = FakeResolve(storage)
    return adapter, media_pool, storage


def test_import_media_not_connected_raises_resolve_connection_error(tmp_path):
    adapter = ResolveScriptAdapter()

    with pytest.raises(ResolveConnectionError):
        adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")


def test_import_media_empty_paths_returns_empty_without_loading_or_importing():
    adapter = ResolveScriptAdapter()
    storage = FakeMediaStorage([FakeMediaItem("clip-1")])
    project_manager = FakeProjectManager(None)
    adapter._resolve = FakeResolve(storage)
    adapter._project_manager = project_manager

    assert adapter.import_media("RLC-E025_MASTER", [], "footage") == []
    assert project_manager.load_calls == []
    assert storage.import_calls == []


def test_import_media_missing_project_raises_project_not_found(tmp_path):
    adapter, _media_pool, _storage = connected_adapter(project=False)

    with pytest.raises(ProjectNotFoundError):
        adapter.import_media("missing", [str(media_file(tmp_path))], "footage")


def test_import_media_one_invalid_path_raises_media_import_error(tmp_path):
    adapter, _media_pool, storage = connected_adapter()
    missing = tmp_path / "missing.mov"

    with pytest.raises(MediaImportError, match="missing.mov"):
        adapter.import_media("RLC-E025_MASTER", [str(missing)], "footage")

    assert adapter._project_manager.load_calls == []
    assert adapter._resolve.media_storage_calls == 0
    assert storage.import_calls == []


def test_import_media_multiple_invalid_paths_are_reported_together(tmp_path):
    adapter, _media_pool, storage = connected_adapter()
    missing_a = tmp_path / "missing-a.mov"
    missing_b = tmp_path / "missing-b.mov"

    with pytest.raises(MediaImportError) as exc_info:
        adapter.import_media("RLC-E025_MASTER", [str(missing_a), str(missing_b)], "footage")

    message = str(exc_info.value)
    assert "missing-a.mov" in message
    assert "missing-b.mov" in message
    assert adapter._project_manager.load_calls == []
    assert adapter._resolve.media_storage_calls == 0
    assert storage.import_calls == []


def test_import_media_reuses_existing_bin(tmp_path):
    existing_bin = FakeFolder("footage")
    media_pool = FakeMediaPool(FakeFolder("root", [existing_bin]))
    adapter, media_pool, _storage = connected_adapter(media_pool=media_pool)

    adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")

    assert media_pool.add_calls == []
    assert media_pool.current_folder is existing_bin


def test_import_media_creates_missing_bin(tmp_path):
    adapter, media_pool, _storage = connected_adapter()

    adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")

    assert media_pool.add_calls[0][1] == "footage"
    assert media_pool.current_folder.GetName() == "footage"


def test_import_media_bin_creation_failure_raises_media_import_error(tmp_path):
    media_pool = FakeMediaPool(FakeFolder("root"), add_result=False)
    adapter, _media_pool, _storage = connected_adapter(media_pool=media_pool)

    with pytest.raises(MediaImportError, match="find or create"):
        adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")


def test_import_media_set_current_folder_failure_raises_media_import_error(tmp_path):
    media_pool = FakeMediaPool(FakeFolder("root"), set_current_result=False)
    adapter, _media_pool, _storage = connected_adapter(media_pool=media_pool)

    with pytest.raises(MediaImportError, match="current folder"):
        adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")


def test_import_media_import_returning_none_raises_media_import_error(tmp_path):
    adapter, _media_pool, _storage = connected_adapter(import_result=None)

    with pytest.raises(MediaImportError, match="failed to import"):
        adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")


def test_import_media_import_returning_empty_list_raises_media_import_error(tmp_path):
    adapter, _media_pool, _storage = connected_adapter(import_result=[])

    with pytest.raises(MediaImportError, match="failed to import"):
        adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")


def test_import_media_partial_import_count_mismatch_raises_media_import_error(tmp_path):
    adapter, _media_pool, _storage = connected_adapter(import_result=[FakeMediaItem("clip-1")])

    with pytest.raises(MediaImportError, match="1 item\\(s\\).*2 path\\(s\\)"):
        adapter.import_media(
            "RLC-E025_MASTER",
            [str(media_file(tmp_path, "a.mov")), str(media_file(tmp_path, "b.mov"))],
            "footage",
        )


def test_import_media_success_returns_get_media_id_values(tmp_path):
    adapter, _media_pool, _storage = connected_adapter(import_result=[FakeMediaItem("media-id-1")])

    clip_ids = adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")

    assert clip_ids == ["media-id-1"]


def test_import_media_uses_get_unique_id_when_media_id_unavailable_or_empty(tmp_path):
    adapter, _media_pool, _storage = connected_adapter(
        import_result=[
            FakeMediaItem("", "unique-1"),
            FakeMediaItem(None, "unique-2", has_media_id=False),
        ]
    )

    clip_ids = adapter.import_media(
        "RLC-E025_MASTER",
        [str(media_file(tmp_path, "a.mov")), str(media_file(tmp_path, "b.mov"))],
        "footage",
    )

    assert clip_ids == ["unique-1", "unique-2"]


def test_import_media_missing_both_id_methods_or_results_raises_media_import_error(tmp_path):
    adapter, _media_pool, _storage = connected_adapter(
        import_result=[FakeMediaItem("", "", has_media_id=False, has_unique_id=False)]
    )

    with pytest.raises(MediaImportError, match="usable media ID"):
        adapter.import_media("RLC-E025_MASTER", [str(media_file(tmp_path))], "footage")


def test_import_media_paths_with_spaces_are_passed_as_normalized_absolute_strings(tmp_path):
    input_file = media_file(tmp_path, "clip with spaces.mov")
    adapter, _media_pool, storage = connected_adapter(import_result=[FakeMediaItem("clip-1")])

    adapter.import_media("RLC-E025_MASTER", [str(input_file)], "footage")

    assert storage.import_calls == [[str(input_file.resolve())]]
