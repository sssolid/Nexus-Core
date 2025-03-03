"""Unit tests for the File Manager."""

import os
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from nexus_core.core.file_manager import FileManager, FileType
from nexus_core.utils.exceptions import FileError


@pytest.fixture
def temp_root_dir():
    """Create a temporary root directory for file testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def file_config(temp_root_dir):
    """Create a file manager configuration for testing."""
    base_dir = os.path.join(temp_root_dir, "data")
    temp_dir = os.path.join(base_dir, "temp")
    plugin_dir = os.path.join(base_dir, "plugins")
    backup_dir = os.path.join(base_dir, "backups")
    
    return {
        "base_directory": base_dir,
        "temp_directory": temp_dir,
        "plugin_data_directory": plugin_dir,
        "backup_directory": backup_dir
    }


@pytest.fixture
def config_manager_mock(file_config):
    """Create a mock ConfigManager for the FileManager."""
    config_manager = MagicMock()
    config_manager.get.return_value = file_config
    return config_manager


@pytest.fixture
def file_manager(config_manager_mock):
    """Create a FileManager for testing."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    file_mgr = FileManager(config_manager_mock, logger_manager)
    file_mgr.initialize()
    yield file_mgr
    file_mgr.shutdown()


def test_file_manager_initialization(config_manager_mock, temp_root_dir):
    """Test that the FileManager initializes correctly."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    file_mgr = FileManager(config_manager_mock, logger_manager)
    file_mgr.initialize()
    
    assert file_mgr.initialized
    assert file_mgr.healthy
    
    # Check directories were created
    base_dir = os.path.join(temp_root_dir, "data")
    temp_dir = os.path.join(base_dir, "temp")
    plugin_dir = os.path.join(base_dir, "plugins")
    backup_dir = os.path.join(base_dir, "backups")
    
    assert os.path.exists(base_dir)
    assert os.path.exists(temp_dir)
    assert os.path.exists(plugin_dir)
    assert os.path.exists(backup_dir)
    
    file_mgr.shutdown()
    assert not file_mgr.initialized


def test_get_file_path(file_manager, temp_root_dir):
    """Test getting file paths for different directory types."""
    # Test base directory path
    path = file_manager.get_file_path("test.txt", "base")
    assert str(path) == os.path.join(temp_root_dir, "data", "test.txt")
    
    # Test temp directory path
    path = file_manager.get_file_path("temp.txt", "temp")
    assert str(path) == os.path.join(temp_root_dir, "data", "temp", "temp.txt")
    
    # Test plugin data directory path
    path = file_manager.get_file_path("plugin.txt", "plugin_data")
    assert str(path) == os.path.join(temp_root_dir, "data", "plugins", "plugin.txt")
    
    # Test backup directory path
    path = file_manager.get_file_path("backup.txt", "backup")
    assert str(path) == os.path.join(temp_root_dir, "data", "backups", "backup.txt")
    
    # Test invalid directory type
    with pytest.raises(FileError):
        file_manager.get_file_path("test.txt", "invalid")


def test_ensure_directory(file_manager, temp_root_dir):
    """Test ensuring a directory exists."""
    # Create a nested directory
    nested_dir = file_manager.ensure_directory("nested/dir", "base")
    assert os.path.exists(nested_dir)
    assert os.path.isdir(nested_dir)


def test_text_file_operations(file_manager, temp_root_dir):
    """Test writing and reading text files."""
    test_content = "This is a test file.\nWith multiple lines."
    
    # Write text file
    file_manager.write_text("test.txt", test_content)
    
    # Check file exists
    base_dir = os.path.join(temp_root_dir, "data")
    assert os.path.exists(os.path.join(base_dir, "test.txt"))
    
    # Read text file
    content = file_manager.read_text("test.txt")
    assert content == test_content
    
    # Test writing to subdirectory
    file_manager.write_text("subdir/test.txt", test_content, create_dirs=True)
    assert os.path.exists(os.path.join(base_dir, "subdir", "test.txt"))
    
    # Test reading from non-existent file
    with pytest.raises(FileError):
        file_manager.read_text("nonexistent.txt")


def test_binary_file_operations(file_manager, temp_root_dir):
    """Test writing and reading binary files."""
    test_content = b'\x00\x01\x02\x03\x04'
    
    # Write binary file
    file_manager.write_binary("test.bin", test_content)
    
    # Check file exists
    base_dir = os.path.join(temp_root_dir, "data")
    assert os.path.exists(os.path.join(base_dir, "test.bin"))
    
    # Read binary file
    content = file_manager.read_binary("test.bin")
    assert content == test_content
    
    # Test reading from non-existent file
    with pytest.raises(FileError):
        file_manager.read_binary("nonexistent.bin")


def test_file_operations_without_initialization():
    """Test file operations before initialization."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    config_manager = MagicMock()
    
    file_mgr = FileManager(config_manager, logger_manager)
    
    with pytest.raises(FileError):
        file_mgr.read_text("test.txt")


def test_list_files(file_manager, temp_root_dir):
    """Test listing files and directories."""
    # Create a directory structure for testing
    base_dir = os.path.join(temp_root_dir, "data")
    file_manager.write_text("file1.txt", "Content 1")
    file_manager.write_text("file2.txt", "Content 2")
    file_manager.ensure_directory("subdir")
    file_manager.write_text("subdir/file3.txt", "Content 3")
    
    # List files in root directory (non-recursive)
    files = file_manager.list_files()
    assert len(files) == 3  # 2 files + 1 dir
    
    # Check we have the expected files
    file_names = [f.name for f in files]
    assert "file1.txt" in file_names
    assert "file2.txt" in file_names
    assert "subdir" in file_names
    
    # List files recursively
    files = file_manager.list_files(recursive=True)
    assert len(files) == 4  # 3 files + 1 dir
    
    # List files with pattern
    files = file_manager.list_files(pattern="*.txt")
    assert len(files) == 2  # Only the txt files in the root dir
    
    # List files without directories
    files = file_manager.list_files(include_dirs=False)
    assert len(files) == 2  # Just the txt files in the root


def test_delete_file(file_manager, temp_root_dir):
    """Test deleting files and directories."""
    # Create test files and directories
    file_manager.write_text("delete_me.txt", "Delete me")
    file_manager.ensure_directory("delete_dir")
    file_manager.write_text("delete_dir/inner.txt", "Inner file")
    
    base_dir = os.path.join(temp_root_dir, "data")
    
    # Check files exist
    assert os.path.exists(os.path.join(base_dir, "delete_me.txt"))
    assert os.path.exists(os.path.join(base_dir, "delete_dir"))
    assert os.path.exists(os.path.join(base_dir, "delete_dir", "inner.txt"))
    
    # Delete file
    file_manager.delete_file("delete_me.txt")
    assert not os.path.exists(os.path.join(base_dir, "delete_me.txt"))
    
    # Delete directory (should delete recursively)
    file_manager.delete_file("delete_dir")
    assert not os.path.exists(os.path.join(base_dir, "delete_dir"))
    
    # Test deleting non-existent file
    with pytest.raises(FileError):
        file_manager.delete_file("nonexistent.txt")


def test_copy_move_file(file_manager, temp_root_dir):
    """Test copying and moving files."""
    test_content = "File to copy and move"
    
    # Create test file
    file_manager.write_text("source.txt", test_content)
    
    base_dir = os.path.join(temp_root_dir, "data")
    
    # Copy file
    file_manager.copy_file("source.txt", "dest.txt")
    assert os.path.exists(os.path.join(base_dir, "source.txt"))
    assert os.path.exists(os.path.join(base_dir, "dest.txt"))
    
    # Verify content was copied
    content = file_manager.read_text("dest.txt")
    assert content == test_content
    
    # Move file
    file_manager.move_file("source.txt", "moved.txt")
    assert not os.path.exists(os.path.join(base_dir, "source.txt"))
    assert os.path.exists(os.path.join(base_dir, "moved.txt"))
    
    # Verify content was preserved
    content = file_manager.read_text("moved.txt")
    assert content == test_content
    
    # Test overwrite protection
    with pytest.raises(FileError):
        file_manager.copy_file("moved.txt", "dest.txt", overwrite=False)
    
    # Test overwriting
    new_content = "New content"
    file_manager.write_text("new_source.txt", new_content)
    file_manager.copy_file("new_source.txt", "dest.txt", overwrite=True)
    content = file_manager.read_text("dest.txt")
    assert content == new_content


def test_create_backup(file_manager, temp_root_dir):
    """Test creating file backups."""
    # Create test file
    test_content = "File to backup"
    file_manager.write_text("backup_me.txt", test_content)
    
    # Create backup
    backup_path = file_manager.create_backup("backup_me.txt")
    
    # Check backup file exists
    backup_dir = os.path.join(temp_root_dir, "data", "backups")
    assert os.path.exists(os.path.join(backup_dir, backup_path))
    
    # Verify backup content
    backup_content = file_manager.read_text(backup_path, "backup")
    assert backup_content == test_content


def test_get_file_info(file_manager, temp_root_dir):
    """Test getting file information."""
    # Create test file
    test_content = "Test file"
    file_manager.write_text("info_test.txt", test_content)
    
    # Get file info
    file_info = file_manager.get_file_info("info_test.txt")
    
    assert file_info.name == "info_test.txt"
    assert file_info.size == len(test_content)
    assert not file_info.is_directory
    assert file_info.file_type == FileType.TEXT
    
    # Create directory and test
    dir_path = file_manager.ensure_directory("info_dir")
    dir_info = file_manager.get_file_info("info_dir")
    
    assert dir_info.name == "info_dir"
    assert dir_info.is_directory


def test_file_manager_status(file_manager):
    """Test getting status from FileManager."""
    status = file_manager.status()
    
    assert status["name"] == "FileManager"
    assert status["initialized"] is True
    assert "directories" in status
    assert "disk_usage" in status
    assert "active_locks" in status
