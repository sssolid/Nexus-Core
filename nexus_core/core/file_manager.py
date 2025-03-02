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
    """Types of files that the File Manager can handle."""
    
    UNKNOWN = "unknown"
    TEXT = "text"
    BINARY = "binary"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    CONFIG = "config"
    LOG = "log"
    DATA = "data"
    TEMP = "temp"
    BACKUP = "backup"


@dataclass
class FileInfo:
    """Information about a file."""
    
    path: str  # Path to the file
    name: str  # Name of the file (without path)
    size: int  # Size in bytes
    created_at: float  # Creation timestamp
    modified_at: float  # Last modification timestamp
    file_type: FileType  # Type of file
    is_directory: bool  # Whether the file is a directory
    content_hash: Optional[str] = None  # SHA-256 hash of the file content
    metadata: Dict[str, Any] = None  # Additional metadata


class FileManager(NexusManager):
    """Manages file system interactions for the application.
    
    The File Manager is responsible for handling file system operations such as
    reading, writing, and managing directories. It provides a standardized way
    for other components to interact with the file system and ensures proper
    error handling, locking, and organization of files.
    """
    
    def __init__(self, config_manager: Any, logger_manager: Any) -> None:
        """Initialize the File Manager.
        
        Args:
            config_manager: The Configuration Manager to use for file settings.
            logger_manager: The Logging Manager to use for logging.
        """
        super().__init__(name="FileManager")
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger("file_manager")
        
        # File paths
        self._base_directory: Optional[pathlib.Path] = None
        self._temp_directory: Optional[pathlib.Path] = None
        self._plugin_data_directory: Optional[pathlib.Path] = None
        self._backup_directory: Optional[pathlib.Path] = None
        
        # Map of file extensions to file types
        self._file_type_mapping: Dict[str, FileType] = {
            # Text files
            ".txt": FileType.TEXT,
            ".md": FileType.TEXT,
            ".csv": FileType.TEXT,
            ".json": FileType.TEXT,
            ".xml": FileType.TEXT,
            ".html": FileType.TEXT,
            ".htm": FileType.TEXT,
            ".css": FileType.TEXT,
            ".js": FileType.TEXT,
            ".py": FileType.TEXT,
            
            # Config files
            ".yaml": FileType.CONFIG,
            ".yml": FileType.CONFIG,
            ".ini": FileType.CONFIG,
            ".conf": FileType.CONFIG,
            ".cfg": FileType.CONFIG,
            ".toml": FileType.CONFIG,
            
            # Log files
            ".log": FileType.LOG,
            
            # Data files
            ".db": FileType.DATA,
            ".sqlite": FileType.DATA,
            ".sqlite3": FileType.DATA,
            ".parquet": FileType.DATA,
            ".avro": FileType.DATA,
            
            # Image files
            ".jpg": FileType.IMAGE,
            ".jpeg": FileType.IMAGE,
            ".png": FileType.IMAGE,
            ".gif": FileType.IMAGE,
            ".bmp": FileType.IMAGE,
            ".svg": FileType.IMAGE,
            ".webp": FileType.IMAGE,
            
            # Document files
            ".pdf": FileType.DOCUMENT,
            ".doc": FileType.DOCUMENT,
            ".docx": FileType.DOCUMENT,
            ".xls": FileType.DOCUMENT,
            ".xlsx": FileType.DOCUMENT,
            ".ppt": FileType.DOCUMENT,
            ".pptx": FileType.DOCUMENT,
            ".odt": FileType.DOCUMENT,
            ".ods": FileType.DOCUMENT,
            
            # Audio files
            ".mp3": FileType.AUDIO,
            ".wav": FileType.AUDIO,
            ".flac": FileType.AUDIO,
            ".ogg": FileType.AUDIO,
            ".aac": FileType.AUDIO,
            
            # Video files
            ".mp4": FileType.VIDEO,
            ".avi": FileType.VIDEO,
            ".mkv": FileType.VIDEO,
            ".mov": FileType.VIDEO,
            ".webm": FileType.VIDEO,
        }
        
        # File locks for thread safety
        self._file_locks: Dict[str, threading.RLock] = {}
        self._locks_lock = threading.RLock()
    
    def initialize(self) -> None:
        """Initialize the File Manager.
        
        Creates necessary directories and sets up file paths based on configuration.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get configuration
            file_config = self._config_manager.get("files", {})
            base_dir = file_config.get("base_directory", "data")
            temp_dir = file_config.get("temp_directory", "data/temp")
            plugin_data_dir = file_config.get("plugin_data_directory", "data/plugins")
            backup_dir = file_config.get("backup_directory", "data/backups")
            
            # Convert to absolute paths if not already
            self._base_directory = pathlib.Path(base_dir).absolute()
            self._temp_directory = pathlib.Path(temp_dir).absolute()
            self._plugin_data_directory = pathlib.Path(plugin_data_dir).absolute()
            self._backup_directory = pathlib.Path(backup_dir).absolute()
            
            # Create directories if they don't exist
            os.makedirs(self._base_directory, exist_ok=True)
            os.makedirs(self._temp_directory, exist_ok=True)
            os.makedirs(self._plugin_data_directory, exist_ok=True)
            os.makedirs(self._backup_directory, exist_ok=True)
            
            # Register for config changes
            self._config_manager.register_listener("files", self._on_config_changed)
            
            self._logger.info(
                f"File Manager initialized with base directory: {self._base_directory}"
            )
            self._initialized = True
            self._healthy = True
        
        except Exception as e:
            self._logger.error(f"Failed to initialize File Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize FileManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def get_file_path(self, path: str, directory_type: str = "base") -> pathlib.Path:
        """Get the absolute path for a file, relative to a specified directory.
        
        Args:
            path: The path to the file, relative to the specified directory.
            directory_type: The type of directory to use as the base. One of:
                            "base", "temp", "plugin_data", "backup".
        
        Returns:
            pathlib.Path: The absolute path to the file.
            
        Raises:
            FileError: If the directory type is invalid or the manager is not initialized.
        """
        if not self._initialized:
            raise FileError(
                "File Manager not initialized",
                file_path=path,
            )
        
        # Get the base directory for the specified type
        if directory_type == "base":
            base_dir = self._base_directory
        elif directory_type == "temp":
            base_dir = self._temp_directory
        elif directory_type == "plugin_data":
            base_dir = self._plugin_data_directory
        elif directory_type == "backup":
            base_dir = self._backup_directory
        else:
            raise FileError(
                f"Invalid directory type: {directory_type}",
                file_path=path,
            )
        
        # Convert the path to an absolute path
        path_obj = pathlib.Path(path)
        if path_obj.is_absolute():
            # Check if the path is within the allowed directories
            for allowed_dir in [
                self._base_directory,
                self._temp_directory,
                self._plugin_data_directory,
                self._backup_directory,
            ]:
                if str(path_obj).startswith(str(allowed_dir)):
                    return path_obj
            
            raise FileError(
                f"Path is outside of allowed directories: {path}",
                file_path=path,
            )
        
        # Join the path with the base directory
        return base_dir / path
    
    def ensure_directory(self, path: str, directory_type: str = "base") -> pathlib.Path:
        """Ensure that a directory exists, creating it if necessary.
        
        Args:
            path: The path to the directory, relative to the specified directory.
            directory_type: The type of directory to use as the base. One of:
                            "base", "temp", "plugin_data", "backup".
        
        Returns:
            pathlib.Path: The absolute path to the directory.
            
        Raises:
            FileError: If the directory cannot be created.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            os.makedirs(full_path, exist_ok=True)
            return full_path
        
        except Exception as e:
            raise FileError(
                f"Failed to create directory: {str(e)}",
                file_path=path,
            ) from e
    
    def read_text(self, path: str, directory_type: str = "base") -> str:
        """Read text from a file.
        
        Args:
            path: The path to the file, relative to the specified directory.
            directory_type: The type of directory to use as the base.
        
        Returns:
            str: The text content of the file.
            
        Raises:
            FileError: If the file cannot be read.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            
            # Get a lock for this file
            lock = self._get_file_lock(str(full_path))
            
            with lock:
                with open(full_path, "r", encoding="utf-8") as f:
                    return f.read()
        
        except Exception as e:
            raise FileError(
                f"Failed to read text file: {str(e)}",
                file_path=str(full_path) if 'full_path' in locals() else path,
            ) from e
    
    def write_text(
        self,
        path: str,
        content: str,
        directory_type: str = "base",
        create_dirs: bool = True,
    ) -> None:
        """Write text to a file.
        
        Args:
            path: The path to the file, relative to the specified directory.
            content: The text content to write.
            directory_type: The type of directory to use as the base.
            create_dirs: Whether to create parent directories if they don't exist.
        
        Raises:
            FileError: If the file cannot be written.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            
            # Create parent directories if needed
            if create_dirs:
                os.makedirs(full_path.parent, exist_ok=True)
            
            # Get a lock for this file
            lock = self._get_file_lock(str(full_path))
            
            with lock:
                # Write to a temporary file, then rename to ensure atomic write
                temp_path = str(full_path) + '.tmp'
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(content)
                
                # Rename the temporary file to the target file
                os.replace(temp_path, full_path)
        
        except Exception as e:
            raise FileError(
                f"Failed to write text file: {str(e)}",
                file_path=str(full_path) if 'full_path' in locals() else path,
            ) from e
    
    def read_binary(self, path: str, directory_type: str = "base") -> bytes:
        """Read binary data from a file.
        
        Args:
            path: The path to the file, relative to the specified directory.
            directory_type: The type of directory to use as the base.
        
        Returns:
            bytes: The binary content of the file.
            
        Raises:
            FileError: If the file cannot be read.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            
            # Get a lock for this file
            lock = self._get_file_lock(str(full_path))
            
            with lock:
                with open(full_path, "rb") as f:
                    return f.read()
        
        except Exception as e:
            raise FileError(
                f"Failed to read binary file: {str(e)}",
                file_path=str(full_path) if 'full_path' in locals() else path,
            ) from e
    
    def write_binary(
        self,
        path: str,
        content: bytes,
        directory_type: str = "base",
        create_dirs: bool = True,
    ) -> None:
        """Write binary data to a file.
        
        Args:
            path: The path to the file, relative to the specified directory.
            content: The binary content to write.
            directory_type: The type of directory to use as the base.
            create_dirs: Whether to create parent directories if they don't exist.
        
        Raises:
            FileError: If the file cannot be written.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            
            # Create parent directories if needed
            if create_dirs:
                os.makedirs(full_path.parent, exist_ok=True)
            
            # Get a lock for this file
            lock = self._get_file_lock(str(full_path))
            
            with lock:
                # Write to a temporary file, then rename to ensure atomic write
                temp_path = str(full_path) + '.tmp'
                with open(temp_path, "wb") as f:
                    f.write(content)
                
                # Rename the temporary file to the target file
                os.replace(temp_path, full_path)
        
        except Exception as e:
            raise FileError(
                f"Failed to write binary file: {str(e)}",
                file_path=str(full_path) if 'full_path' in locals() else path,
            ) from e
    
    def list_files(
        self,
        path: str = "",
        directory_type: str = "base",
        recursive: bool = False,
        include_dirs: bool = True,
        pattern: Optional[str] = None,
    ) -> List[FileInfo]:
        """List files in a directory.
        
        Args:
            path: The path to the directory, relative to the specified directory.
            directory_type: The type of directory to use as the base.
            recursive: Whether to list files in subdirectories recursively.
            include_dirs: Whether to include directories in the results.
            pattern: Optional glob pattern to filter files by name.
        
        Returns:
            List[FileInfo]: Information about the files in the directory.
            
        Raises:
            FileError: If the directory cannot be listed.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            
            if not full_path.is_dir():
                raise FileError(
                    f"Path is not a directory: {full_path}",
                    file_path=str(full_path),
                )
            
            result: List[FileInfo] = []
            
            # Function to process a single file or directory
            def process_path(p: pathlib.Path) -> None:
                try:
                    stat = p.stat()
                    is_dir = p.is_dir()
                    
                    if is_dir and not include_dirs:
                        return
                    
                    file_info = FileInfo(
                        path=str(p),
                        name=p.name,
                        size=stat.st_size,
                        created_at=stat.st_ctime,
                        modified_at=stat.st_mtime,
                        file_type=self._get_file_type(p),
                        is_directory=is_dir,
                        metadata={},
                    )
                    
                    result.append(file_info)
                
                except Exception as e:
                    self._logger.warning(
                        f"Failed to get info for {p}: {str(e)}",
                        extra={"file_path": str(p)},
                    )
            
            # List the directory
            if recursive:
                # Use pathlib.Path.glob with recursive option
                pattern_to_use = pattern or "**/*"
                for p in full_path.glob(pattern_to_use):
                    process_path(p)
            else:
                # Use pathlib.Path.iterdir for non-recursive listing
                for p in full_path.iterdir():
                    if pattern and not p.match(pattern):
                        continue
                    process_path(p)
            
            return result
        
        except FileError:
            # Re-raise FileError exceptions
            raise
        
        except Exception as e:
            raise FileError(
                f"Failed to list directory: {str(e)}",
                file_path=str(full_path) if 'full_path' in locals() else path,
            ) from e
    
    def get_file_info(self, path: str, directory_type: str = "base") -> FileInfo:
        """Get information about a file.
        
        Args:
            path: The path to the file, relative to the specified directory.
            directory_type: The type of directory to use as the base.
        
        Returns:
            FileInfo: Information about the file.
            
        Raises:
            FileError: If the file information cannot be retrieved.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            
            if not full_path.exists():
                raise FileError(
                    f"File does not exist: {full_path}",
                    file_path=str(full_path),
                )
            
            stat = full_path.stat()
            
            return FileInfo(
                path=str(full_path),
                name=full_path.name,
                size=stat.st_size,
                created_at=stat.st_ctime,
                modified_at=stat.st_mtime,
                file_type=self._get_file_type(full_path),
                is_directory=full_path.is_dir(),
                metadata={},
            )
        
        except FileError:
            # Re-raise FileError exceptions
            raise
        
        except Exception as e:
            raise FileError(
                f"Failed to get file info: {str(e)}",
                file_path=str(full_path) if 'full_path' in locals() else path,
            ) from e
    
    def delete_file(self, path: str, directory_type: str = "base") -> None:
        """Delete a file.
        
        Args:
            path: The path to the file, relative to the specified directory.
            directory_type: The type of directory to use as the base.
        
        Raises:
            FileError: If the file cannot be deleted.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            
            if not full_path.exists():
                raise FileError(
                    f"File does not exist: {full_path}",
                    file_path=str(full_path),
                )
            
            # Get a lock for this file
            lock = self._get_file_lock(str(full_path))
            
            with lock:
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
            
            # Release the lock
            self._release_file_lock(str(full_path))
        
        except FileError:
            # Re-raise FileError exceptions
            raise
        
        except Exception as e:
            raise FileError(
                f"Failed to delete file: {str(e)}",
                file_path=str(full_path) if 'full_path' in locals() else path,
            ) from e
    
    def copy_file(
        self,
        source_path: str,
        dest_path: str,
        source_dir_type: str = "base",
        dest_dir_type: str = "base",
        overwrite: bool = False,
    ) -> None:
        """Copy a file from one location to another.
        
        Args:
            source_path: The path to the source file.
            dest_path: The path to the destination file.
            source_dir_type: The type of directory to use as the base for the source.
            dest_dir_type: The type of directory to use as the base for the destination.
            overwrite: Whether to overwrite the destination file if it exists.
        
        Raises:
            FileError: If the file cannot be copied.
        """
        try:
            source_full_path = self.get_file_path(source_path, source_dir_type)
            dest_full_path = self.get_file_path(dest_path, dest_dir_type)
            
            if not source_full_path.exists():
                raise FileError(
                    f"Source file does not exist: {source_full_path}",
                    file_path=str(source_full_path),
                )
            
            if dest_full_path.exists() and not overwrite:
                raise FileError(
                    f"Destination file already exists: {dest_full_path}",
                    file_path=str(dest_full_path),
                )
            
            # Create parent directories if needed
            os.makedirs(dest_full_path.parent, exist_ok=True)
            
            # Get locks for both files
            source_lock = self._get_file_lock(str(source_full_path))
            dest_lock = self._get_file_lock(str(dest_full_path))
            
            # Acquire locks in a consistent order to avoid deadlocks
            first_lock, second_lock = sorted([source_lock, dest_lock], key=id)
            
            with first_lock:
                with second_lock:
                    if source_full_path.is_dir():
                        shutil.copytree(source_full_path, dest_full_path, dirs_exist_ok=overwrite)
                    else:
                        shutil.copy2(source_full_path, dest_full_path)
        
        except FileError:
            # Re-raise FileError exceptions
            raise
        
        except Exception as e:
            raise FileError(
                f"Failed to copy file: {str(e)}",
                file_path=f"{source_path} -> {dest_path}",
            ) from e
    
    def move_file(
        self,
        source_path: str,
        dest_path: str,
        source_dir_type: str = "base",
        dest_dir_type: str = "base",
        overwrite: bool = False,
    ) -> None:
        """Move a file from one location to another.
        
        Args:
            source_path: The path to the source file.
            dest_path: The path to the destination file.
            source_dir_type: The type of directory to use as the base for the source.
            dest_dir_type: The type of directory to use as the base for the destination.
            overwrite: Whether to overwrite the destination file if it exists.
        
        Raises:
            FileError: If the file cannot be moved.
        """
        try:
            source_full_path = self.get_file_path(source_path, source_dir_type)
            dest_full_path = self.get_file_path(dest_path, dest_dir_type)
            
            if not source_full_path.exists():
                raise FileError(
                    f"Source file does not exist: {source_full_path}",
                    file_path=str(source_full_path),
                )
            
            if dest_full_path.exists() and not overwrite:
                raise FileError(
                    f"Destination file already exists: {dest_full_path}",
                    file_path=str(dest_full_path),
                )
            
            # Create parent directories if needed
            os.makedirs(dest_full_path.parent, exist_ok=True)
            
            # Get locks for both files
            source_lock = self._get_file_lock(str(source_full_path))
            dest_lock = self._get_file_lock(str(dest_full_path))
            
            # Acquire locks in a consistent order to avoid deadlocks
            first_lock, second_lock = sorted([source_lock, dest_lock], key=id)
            
            with first_lock:
                with second_lock:
                    # Use shutil.move for both files and directories
                    shutil.move(source_full_path, dest_full_path)
            
            # Release locks
            self._release_file_lock(str(source_full_path))
            self._release_file_lock(str(dest_full_path))
        
        except FileError:
            # Re-raise FileError exceptions
            raise
        
        except Exception as e:
            raise FileError(
                f"Failed to move file: {str(e)}",
                file_path=f"{source_path} -> {dest_path}",
            ) from e
    
    def create_backup(self, path: str, directory_type: str = "base") -> str:
        """Create a backup of a file in the backup directory.
        
        Args:
            path: The path to the file to back up.
            directory_type: The type of directory to use as the base.
        
        Returns:
            str: The path to the backup file, relative to the backup directory.
            
        Raises:
            FileError: If the backup cannot be created.
        """
        try:
            source_full_path = self.get_file_path(path, directory_type)
            
            if not source_full_path.exists():
                raise FileError(
                    f"Source file does not exist: {source_full_path}",
                    file_path=str(source_full_path),
                )
            
            # Generate a backup filename with timestamp
            backup_name = (
                f"{source_full_path.stem}_{int(time.time())}{source_full_path.suffix}"
            )
            
            # Backup subdirectory structure mirrors the original path relative to the base
            rel_path = source_full_path.relative_to(self.get_file_path("", directory_type))
            backup_path = rel_path.parent / backup_name
            
            # Copy the file to the backup location
            self.copy_file(
                source_path=str(source_full_path),
                dest_path=str(backup_path),
                source_dir_type=directory_type,
                dest_dir_type="backup",
                overwrite=True,
            )
            
            return str(backup_path)
        
        except FileError:
            # Re-raise FileError exceptions
            raise
        
        except Exception as e:
            raise FileError(
                f"Failed to create backup: {str(e)}",
                file_path=path,
            ) from e
    
    def create_temp_file(self, prefix: str = "", suffix: str = "") -> Tuple[str, BinaryIO]:
        """Create a temporary file in the temp directory.
        
        Args:
            prefix: Optional prefix for the filename.
            suffix: Optional suffix for the filename.
        
        Returns:
            Tuple[str, BinaryIO]: The path to the temp file and an open file object.
            
        Raises:
            FileError: If the temporary file cannot be created.
        """
        try:
            # Generate a unique filename
            temp_name = f"{prefix}{int(time.time())}_{os.urandom(4).hex()}{suffix}"
            temp_path = self.get_file_path(temp_name, "temp")
            
            # Create parent directory if needed
            os.makedirs(temp_path.parent, exist_ok=True)
            
            # Open the file
            file_obj = open(temp_path, "wb+")
            
            return str(temp_path), file_obj
        
        except Exception as e:
            raise FileError(
                f"Failed to create temporary file: {str(e)}",
                file_path=temp_name if 'temp_name' in locals() else f"{prefix}*{suffix}",
            ) from e
    
    def compute_file_hash(self, path: str, directory_type: str = "base") -> str:
        """Compute the SHA-256 hash of a file's contents.
        
        Args:
            path: The path to the file.
            directory_type: The type of directory to use as the base.
        
        Returns:
            str: The hexadecimal hash of the file.
            
        Raises:
            FileError: If the hash cannot be computed.
        """
        try:
            full_path = self.get_file_path(path, directory_type)
            
            if not full_path.exists() or full_path.is_dir():
                raise FileError(
                    f"Cannot compute hash for non-existent or directory: {full_path}",
                    file_path=str(full_path),
                )
            
            # Get a lock for this file
            lock = self._get_file_lock(str(full_path))
            
            with lock:
                # Compute the hash in chunks to handle large files
                hasher = hashlib.sha256()
                with open(full_path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        hasher.update(chunk)
                
                return hasher.hexdigest()
        
        except FileError:
            # Re-raise FileError exceptions
            raise
        
        except Exception as e:
            raise FileError(
                f"Failed to compute file hash: {str(e)}",
                file_path=str(full_path) if 'full_path' in locals() else path,
            ) from e
    
    def _get_file_type(self, path: pathlib.Path) -> FileType:
        """Determine the type of a file based on its extension.
        
        Args:
            path: The path to the file.
        
        Returns:
            FileType: The type of the file.
        """
        if path.is_dir():
            return FileType.UNKNOWN
        
        extension = path.suffix.lower()
        return self._file_type_mapping.get(extension, FileType.UNKNOWN)
    
    def _get_file_lock(self, path: str) -> threading.RLock:
        """Get a lock for a file path, creating one if it doesn't exist.
        
        Args:
            path: The absolute path to the file.
        
        Returns:
            threading.RLock: A lock for the file.
        """
        with self._locks_lock:
            if path not in self._file_locks:
                self._file_locks[path] = threading.RLock()
            
            return self._file_locks[path]
    
    def _release_file_lock(self, path: str) -> None:
        """Release a file lock if it exists and is not currently held.
        
        Args:
            path: The absolute path to the file.
        """
        with self._locks_lock:
            if path in self._file_locks:
                # We can't easily check if a lock is held, so we'll just remove it
                # from the dictionary if the file no longer exists
                if not os.path.exists(path):
                    del self._file_locks[path]
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for the file system.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        # Most directory changes require a restart to take effect
        if key.startswith("files."):
            self._logger.warning(
                f"Configuration change to {key} requires restart to take full effect",
            )
    
    def shutdown(self) -> None:
        """Shut down the File Manager.
        
        Clears file locks and cleans up resources.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down File Manager")
            
            # Clear file locks
            with self._locks_lock:
                self._file_locks.clear()
            
            # Unregister config listener
            self._config_manager.unregister_listener("files", self._on_config_changed)
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("File Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down File Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down FileManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the File Manager.
        
        Returns:
            Dict[str, Any]: Status information about the File Manager.
        """
        status = super().status()
        
        if self._initialized:
            # Get disk usage information for the base directory
            try:
                total, used, free = shutil.disk_usage(self._base_directory)
                disk_percent = (used / total) * 100 if total > 0 else 0
            except:
                total = used = free = 0
                disk_percent = 0
            
            # Count active locks
            with self._locks_lock:
                lock_count = len(self._file_locks)
            
            status.update({
                "directories": {
                    "base": str(self._base_directory),
                    "temp": str(self._temp_directory),
                    "plugin_data": str(self._plugin_data_directory),
                    "backup": str(self._backup_directory),
                },
                "disk_usage": {
                    "total_gb": round(total / (1024**3), 2),
                    "used_gb": round(used / (1024**3), 2),
                    "free_gb": round(free / (1024**3), 2),
                    "percent_used": round(disk_percent, 2),
                },
                "active_locks": lock_count,
            })
        
        return status
