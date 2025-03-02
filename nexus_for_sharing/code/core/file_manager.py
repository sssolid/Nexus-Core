from __future__ import annotations
import hashlib
import os
import pathlib
import shutil
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, BinaryIO, Dict, List, Optional, Set, Tuple, Union, cast
from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import FileError, ManagerInitializationError, ManagerShutdownError
class FileType(Enum):
    UNKNOWN = 'unknown'
    TEXT = 'text'
    BINARY = 'binary'
    IMAGE = 'image'
    DOCUMENT = 'document'
    AUDIO = 'audio'
    VIDEO = 'video'
    CONFIG = 'config'
    LOG = 'log'
    DATA = 'data'
    TEMP = 'temp'
    BACKUP = 'backup'
@dataclass
class FileInfo:
    path: str
    name: str
    size: int
    created_at: float
    modified_at: float
    file_type: FileType
    is_directory: bool
    content_hash: Optional[str] = None
    metadata: Dict[str, Any] = None
class FileManager(NexusManager):
    def __init__(self, config_manager: Any, logger_manager: Any) -> None:
        super().__init__(name='FileManager')
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger('file_manager')
        self._base_directory: Optional[pathlib.Path] = None
        self._temp_directory: Optional[pathlib.Path] = None
        self._plugin_data_directory: Optional[pathlib.Path] = None
        self._backup_directory: Optional[pathlib.Path] = None
        self._file_type_mapping: Dict[str, FileType] = {'.txt': FileType.TEXT, '.md': FileType.TEXT, '.csv': FileType.TEXT, '.json': FileType.TEXT, '.xml': FileType.TEXT, '.html': FileType.TEXT, '.htm': FileType.TEXT, '.css': FileType.TEXT, '.js': FileType.TEXT, '.py': FileType.TEXT, '.yaml': FileType.CONFIG, '.yml': FileType.CONFIG, '.ini': FileType.CONFIG, '.conf': FileType.CONFIG, '.cfg': FileType.CONFIG, '.toml': FileType.CONFIG, '.log': FileType.LOG, '.db': FileType.DATA, '.sqlite': FileType.DATA, '.sqlite3': FileType.DATA, '.parquet': FileType.DATA, '.avro': FileType.DATA, '.jpg': FileType.IMAGE, '.jpeg': FileType.IMAGE, '.png': FileType.IMAGE, '.gif': FileType.IMAGE, '.bmp': FileType.IMAGE, '.svg': FileType.IMAGE, '.webp': FileType.IMAGE, '.pdf': FileType.DOCUMENT, '.doc': FileType.DOCUMENT, '.docx': FileType.DOCUMENT, '.xls': FileType.DOCUMENT, '.xlsx': FileType.DOCUMENT, '.ppt': FileType.DOCUMENT, '.pptx': FileType.DOCUMENT, '.odt': FileType.DOCUMENT, '.ods': FileType.DOCUMENT, '.mp3': FileType.AUDIO, '.wav': FileType.AUDIO, '.flac': FileType.AUDIO, '.ogg': FileType.AUDIO, '.aac': FileType.AUDIO, '.mp4': FileType.VIDEO, '.avi': FileType.VIDEO, '.mkv': FileType.VIDEO, '.mov': FileType.VIDEO, '.webm': FileType.VIDEO}
        self._file_locks: Dict[str, threading.RLock] = {}
        self._locks_lock = threading.RLock()
    def initialize(self) -> None:
        try:
            file_config = self._config_manager.get('files', {})
            base_dir = file_config.get('base_directory', 'data')
            temp_dir = file_config.get('temp_directory', 'data/temp')
            plugin_data_dir = file_config.get('plugin_data_directory', 'data/plugins')
            backup_dir = file_config.get('backup_directory', 'data/backups')
            self._base_directory = pathlib.Path(base_dir).absolute()
            self._temp_directory = pathlib.Path(temp_dir).absolute()
            self._plugin_data_directory = pathlib.Path(plugin_data_dir).absolute()
            self._backup_directory = pathlib.Path(backup_dir).absolute()
            os.makedirs(self._base_directory, exist_ok=True)
            os.makedirs(self._temp_directory, exist_ok=True)
            os.makedirs(self._plugin_data_directory, exist_ok=True)
            os.makedirs(self._backup_directory, exist_ok=True)
            self._config_manager.register_listener('files', self._on_config_changed)
            self._logger.info(f'File Manager initialized with base directory: {self._base_directory}')
            self._initialized = True
            self._healthy = True
        except Exception as e:
            self._logger.error(f'Failed to initialize File Manager: {str(e)}')
            raise ManagerInitializationError(f'Failed to initialize FileManager: {str(e)}', manager_name=self.name) from e
    def get_file_path(self, path: str, directory_type: str='base') -> pathlib.Path:
        if not self._initialized:
            raise FileError('File Manager not initialized', file_path=path)
        if directory_type == 'base':
            base_dir = self._base_directory
        elif directory_type == 'temp':
            base_dir = self._temp_directory
        elif directory_type == 'plugin_data':
            base_dir = self._plugin_data_directory
        elif directory_type == 'backup':
            base_dir = self._backup_directory
        else:
            raise FileError(f'Invalid directory type: {directory_type}', file_path=path)
        path_obj = pathlib.Path(path)
        if path_obj.is_absolute():
            for allowed_dir in [self._base_directory, self._temp_directory, self._plugin_data_directory, self._backup_directory]:
                if str(path_obj).startswith(str(allowed_dir)):
                    return path_obj
            raise FileError(f'Path is outside of allowed directories: {path}', file_path=path)
        return base_dir / path
    def ensure_directory(self, path: str, directory_type: str='base') -> pathlib.Path:
        try:
            full_path = self.get_file_path(path, directory_type)
            os.makedirs(full_path, exist_ok=True)
            return full_path
        except Exception as e:
            raise FileError(f'Failed to create directory: {str(e)}', file_path=path) from e
    def read_text(self, path: str, directory_type: str='base') -> str:
        try:
            full_path = self.get_file_path(path, directory_type)
            lock = self._get_file_lock(str(full_path))
            with lock:
                with open(full_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            raise FileError(f'Failed to read text file: {str(e)}', file_path=str(full_path) if 'full_path' in locals() else path) from e
    def write_text(self, path: str, content: str, directory_type: str='base', create_dirs: bool=True) -> None:
        try:
            full_path = self.get_file_path(path, directory_type)
            if create_dirs:
                os.makedirs(full_path.parent, exist_ok=True)
            lock = self._get_file_lock(str(full_path))
            with lock:
                temp_path = str(full_path) + '.tmp'
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                os.replace(temp_path, full_path)
        except Exception as e:
            raise FileError(f'Failed to write text file: {str(e)}', file_path=str(full_path) if 'full_path' in locals() else path) from e
    def read_binary(self, path: str, directory_type: str='base') -> bytes:
        try:
            full_path = self.get_file_path(path, directory_type)
            lock = self._get_file_lock(str(full_path))
            with lock:
                with open(full_path, 'rb') as f:
                    return f.read()
        except Exception as e:
            raise FileError(f'Failed to read binary file: {str(e)}', file_path=str(full_path) if 'full_path' in locals() else path) from e
    def write_binary(self, path: str, content: bytes, directory_type: str='base', create_dirs: bool=True) -> None:
        try:
            full_path = self.get_file_path(path, directory_type)
            if create_dirs:
                os.makedirs(full_path.parent, exist_ok=True)
            lock = self._get_file_lock(str(full_path))
            with lock:
                temp_path = str(full_path) + '.tmp'
                with open(temp_path, 'wb') as f:
                    f.write(content)
                os.replace(temp_path, full_path)
        except Exception as e:
            raise FileError(f'Failed to write binary file: {str(e)}', file_path=str(full_path) if 'full_path' in locals() else path) from e
    def list_files(self, path: str='', directory_type: str='base', recursive: bool=False, include_dirs: bool=True, pattern: Optional[str]=None) -> List[FileInfo]:
        try:
            full_path = self.get_file_path(path, directory_type)
            if not full_path.is_dir():
                raise FileError(f'Path is not a directory: {full_path}', file_path=str(full_path))
            result: List[FileInfo] = []
            def process_path(p: pathlib.Path) -> None:
                try:
                    stat = p.stat()
                    is_dir = p.is_dir()
                    if is_dir and (not include_dirs):
                        return
                    file_info = FileInfo(path=str(p), name=p.name, size=stat.st_size, created_at=stat.st_ctime, modified_at=stat.st_mtime, file_type=self._get_file_type(p), is_directory=is_dir, metadata={})
                    result.append(file_info)
                except Exception as e:
                    self._logger.warning(f'Failed to get info for {p}: {str(e)}', extra={'file_path': str(p)})
            if recursive:
                pattern_to_use = pattern or '**/*'
                for p in full_path.glob(pattern_to_use):
                    process_path(p)
            else:
                for p in full_path.iterdir():
                    if pattern and (not p.match(pattern)):
                        continue
                    process_path(p)
            return result
        except FileError:
            raise
        except Exception as e:
            raise FileError(f'Failed to list directory: {str(e)}', file_path=str(full_path) if 'full_path' in locals() else path) from e
    def get_file_info(self, path: str, directory_type: str='base') -> FileInfo:
        try:
            full_path = self.get_file_path(path, directory_type)
            if not full_path.exists():
                raise FileError(f'File does not exist: {full_path}', file_path=str(full_path))
            stat = full_path.stat()
            return FileInfo(path=str(full_path), name=full_path.name, size=stat.st_size, created_at=stat.st_ctime, modified_at=stat.st_mtime, file_type=self._get_file_type(full_path), is_directory=full_path.is_dir(), metadata={})
        except FileError:
            raise
        except Exception as e:
            raise FileError(f'Failed to get file info: {str(e)}', file_path=str(full_path) if 'full_path' in locals() else path) from e
    def delete_file(self, path: str, directory_type: str='base') -> None:
        try:
            full_path = self.get_file_path(path, directory_type)
            if not full_path.exists():
                raise FileError(f'File does not exist: {full_path}', file_path=str(full_path))
            lock = self._get_file_lock(str(full_path))
            with lock:
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
            self._release_file_lock(str(full_path))
        except FileError:
            raise
        except Exception as e:
            raise FileError(f'Failed to delete file: {str(e)}', file_path=str(full_path) if 'full_path' in locals() else path) from e
    def copy_file(self, source_path: str, dest_path: str, source_dir_type: str='base', dest_dir_type: str='base', overwrite: bool=False) -> None:
        try:
            source_full_path = self.get_file_path(source_path, source_dir_type)
            dest_full_path = self.get_file_path(dest_path, dest_dir_type)
            if not source_full_path.exists():
                raise FileError(f'Source file does not exist: {source_full_path}', file_path=str(source_full_path))
            if dest_full_path.exists() and (not overwrite):
                raise FileError(f'Destination file already exists: {dest_full_path}', file_path=str(dest_full_path))
            os.makedirs(dest_full_path.parent, exist_ok=True)
            source_lock = self._get_file_lock(str(source_full_path))
            dest_lock = self._get_file_lock(str(dest_full_path))
            first_lock, second_lock = sorted([source_lock, dest_lock], key=id)
            with first_lock:
                with second_lock:
                    if source_full_path.is_dir():
                        shutil.copytree(source_full_path, dest_full_path, dirs_exist_ok=overwrite)
                    else:
                        shutil.copy2(source_full_path, dest_full_path)
        except FileError:
            raise
        except Exception as e:
            raise FileError(f'Failed to copy file: {str(e)}', file_path=f'{source_path} -> {dest_path}') from e
    def move_file(self, source_path: str, dest_path: str, source_dir_type: str='base', dest_dir_type: str='base', overwrite: bool=False) -> None:
        try:
            source_full_path = self.get_file_path(source_path, source_dir_type)
            dest_full_path = self.get_file_path(dest_path, dest_dir_type)
            if not source_full_path.exists():
                raise FileError(f'Source file does not exist: {source_full_path}', file_path=str(source_full_path))
            if dest_full_path.exists() and (not overwrite):
                raise FileError(f'Destination file already exists: {dest_full_path}', file_path=str(dest_full_path))
            os.makedirs(dest_full_path.parent, exist_ok=True)
            source_lock = self._get_file_lock(str(source_full_path))
            dest_lock = self._get_file_lock(str(dest_full_path))
            first_lock, second_lock = sorted([source_lock, dest_lock], key=id)
            with first_lock:
                with second_lock:
                    shutil.move(source_full_path, dest_full_path)
            self._release_file_lock(str(source_full_path))
            self._release_file_lock(str(dest_full_path))
        except FileError:
            raise
        except Exception as e:
            raise FileError(f'Failed to move file: {str(e)}', file_path=f'{source_path} -> {dest_path}') from e
    def create_backup(self, path: str, directory_type: str='base') -> str:
        try:
            source_full_path = self.get_file_path(path, directory_type)
            if not source_full_path.exists():
                raise FileError(f'Source file does not exist: {source_full_path}', file_path=str(source_full_path))
            backup_name = f'{source_full_path.stem}_{int(time.time())}{source_full_path.suffix}'
            rel_path = source_full_path.relative_to(self.get_file_path('', directory_type))
            backup_path = rel_path.parent / backup_name
            self.copy_file(source_path=str(source_full_path), dest_path=str(backup_path), source_dir_type=directory_type, dest_dir_type='backup', overwrite=True)
            return str(backup_path)
        except FileError:
            raise
        except Exception as e:
            raise FileError(f'Failed to create backup: {str(e)}', file_path=path) from e
    def create_temp_file(self, prefix: str='', suffix: str='') -> Tuple[str, BinaryIO]:
        try:
            temp_name = f'{prefix}{int(time.time())}_{os.urandom(4).hex()}{suffix}'
            temp_path = self.get_file_path(temp_name, 'temp')
            os.makedirs(temp_path.parent, exist_ok=True)
            file_obj = open(temp_path, 'wb+')
            return (str(temp_path), file_obj)
        except Exception as e:
            raise FileError(f'Failed to create temporary file: {str(e)}', file_path=temp_name if 'temp_name' in locals() else f'{prefix}*{suffix}') from e
    def compute_file_hash(self, path: str, directory_type: str='base') -> str:
        try:
            full_path = self.get_file_path(path, directory_type)
            if not full_path.exists() or full_path.is_dir():
                raise FileError(f'Cannot compute hash for non-existent or directory: {full_path}', file_path=str(full_path))
            lock = self._get_file_lock(str(full_path))
            with lock:
                hasher = hashlib.sha256()
                with open(full_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b''):
                        hasher.update(chunk)
                return hasher.hexdigest()
        except FileError:
            raise
        except Exception as e:
            raise FileError(f'Failed to compute file hash: {str(e)}', file_path=str(full_path) if 'full_path' in locals() else path) from e
    def _get_file_type(self, path: pathlib.Path) -> FileType:
        if path.is_dir():
            return FileType.UNKNOWN
        extension = path.suffix.lower()
        return self._file_type_mapping.get(extension, FileType.UNKNOWN)
    def _get_file_lock(self, path: str) -> threading.RLock:
        with self._locks_lock:
            if path not in self._file_locks:
                self._file_locks[path] = threading.RLock()
            return self._file_locks[path]
    def _release_file_lock(self, path: str) -> None:
        with self._locks_lock:
            if path in self._file_locks:
                if not os.path.exists(path):
                    del self._file_locks[path]
    def _on_config_changed(self, key: str, value: Any) -> None:
        if key.startswith('files.'):
            self._logger.warning(f'Configuration change to {key} requires restart to take full effect')
    def shutdown(self) -> None:
        if not self._initialized:
            return
        try:
            self._logger.info('Shutting down File Manager')
            with self._locks_lock:
                self._file_locks.clear()
            self._config_manager.unregister_listener('files', self._on_config_changed)
            self._initialized = False
            self._healthy = False
            self._logger.info('File Manager shut down successfully')
        except Exception as e:
            self._logger.error(f'Failed to shut down File Manager: {str(e)}')
            raise ManagerShutdownError(f'Failed to shut down FileManager: {str(e)}', manager_name=self.name) from e
    def status(self) -> Dict[str, Any]:
        status = super().status()
        if self._initialized:
            try:
                total, used, free = shutil.disk_usage(self._base_directory)
                disk_percent = used / total * 100 if total > 0 else 0
            except:
                total = used = free = 0
                disk_percent = 0
            with self._locks_lock:
                lock_count = len(self._file_locks)
            status.update({'directories': {'base': str(self._base_directory), 'temp': str(self._temp_directory), 'plugin_data': str(self._plugin_data_directory), 'backup': str(self._backup_directory)}, 'disk_usage': {'total_gb': round(total / 1024 ** 3, 2), 'used_gb': round(used / 1024 ** 3, 2), 'free_gb': round(free / 1024 ** 3, 2), 'percent_used': round(disk_percent, 2)}, 'active_locks': lock_count})
        return status