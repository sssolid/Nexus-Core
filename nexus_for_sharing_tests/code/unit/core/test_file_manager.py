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
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)
@pytest.fixture
def file_config(temp_root_dir):
    base_dir = os.path.join(temp_root_dir, 'data')
    temp_dir = os.path.join(base_dir, 'temp')
    plugin_dir = os.path.join(base_dir, 'plugins')
    backup_dir = os.path.join(base_dir, 'backups')
    return {'base_directory': base_dir, 'temp_directory': temp_dir, 'plugin_data_directory': plugin_dir, 'backup_directory': backup_dir}
@pytest.fixture
def config_manager_mock(file_config):
    config_manager = MagicMock()
    config_manager.get.return_value = file_config
    return config_manager
@pytest.fixture
def file_manager(config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    file_mgr = FileManager(config_manager_mock, logger_manager)
    file_mgr.initialize()
    yield file_mgr
    file_mgr.shutdown()
def test_file_manager_initialization(config_manager_mock, temp_root_dir):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    file_mgr = FileManager(config_manager_mock, logger_manager)
    file_mgr.initialize()
    assert file_mgr.initialized
    assert file_mgr.healthy
    base_dir = os.path.join(temp_root_dir, 'data')
    temp_dir = os.path.join(base_dir, 'temp')
    plugin_dir = os.path.join(base_dir, 'plugins')
    backup_dir = os.path.join(base_dir, 'backups')
    assert os.path.exists(base_dir)
    assert os.path.exists(temp_dir)
    assert os.path.exists(plugin_dir)
    assert os.path.exists(backup_dir)
    file_mgr.shutdown()
    assert not file_mgr.initialized
def test_get_file_path(file_manager, temp_root_dir):
    path = file_manager.get_file_path('test.txt', 'base')
    assert str(path) == os.path.join(temp_root_dir, 'data', 'test.txt')
    path = file_manager.get_file_path('temp.txt', 'temp')
    assert str(path) == os.path.join(temp_root_dir, 'data', 'temp', 'temp.txt')
    path = file_manager.get_file_path('plugin.txt', 'plugin_data')
    assert str(path) == os.path.join(temp_root_dir, 'data', 'plugins', 'plugin.txt')
    path = file_manager.get_file_path('backup.txt', 'backup')
    assert str(path) == os.path.join(temp_root_dir, 'data', 'backups', 'backup.txt')
    with pytest.raises(FileError):
        file_manager.get_file_path('test.txt', 'invalid')
def test_ensure_directory(file_manager, temp_root_dir):
    nested_dir = file_manager.ensure_directory('nested/dir', 'base')
    assert os.path.exists(nested_dir)
    assert os.path.isdir(nested_dir)
def test_text_file_operations(file_manager, temp_root_dir):
    test_content = 'This is a test file.\nWith multiple lines.'
    file_manager.write_text('test.txt', test_content)
    base_dir = os.path.join(temp_root_dir, 'data')
    assert os.path.exists(os.path.join(base_dir, 'test.txt'))
    content = file_manager.read_text('test.txt')
    assert content == test_content
    file_manager.write_text('subdir/test.txt', test_content, create_dirs=True)
    assert os.path.exists(os.path.join(base_dir, 'subdir', 'test.txt'))
    with pytest.raises(FileError):
        file_manager.read_text('nonexistent.txt')
def test_binary_file_operations(file_manager, temp_root_dir):
    test_content = b'\x00\x01\x02\x03\x04'
    file_manager.write_binary('test.bin', test_content)
    base_dir = os.path.join(temp_root_dir, 'data')
    assert os.path.exists(os.path.join(base_dir, 'test.bin'))
    content = file_manager.read_binary('test.bin')
    assert content == test_content
    with pytest.raises(FileError):
        file_manager.read_binary('nonexistent.bin')
def test_file_operations_without_initialization():
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    config_manager = MagicMock()
    file_mgr = FileManager(config_manager, logger_manager)
    with pytest.raises(FileError):
        file_mgr.read_text('test.txt')
def test_list_files(file_manager, temp_root_dir):
    base_dir = os.path.join(temp_root_dir, 'data')
    file_manager.write_text('file1.txt', 'Content 1')
    file_manager.write_text('file2.txt', 'Content 2')
    file_manager.ensure_directory('subdir')
    file_manager.write_text('subdir/file3.txt', 'Content 3')
    files = file_manager.list_files()
    assert len(files) == 3
    file_names = [f.name for f in files]
    assert 'file1.txt' in file_names
    assert 'file2.txt' in file_names
    assert 'subdir' in file_names
    files = file_manager.list_files(recursive=True)
    assert len(files) == 4
    files = file_manager.list_files(pattern='*.txt')
    assert len(files) == 2
    files = file_manager.list_files(include_dirs=False)
    assert len(files) == 2
def test_delete_file(file_manager, temp_root_dir):
    file_manager.write_text('delete_me.txt', 'Delete me')
    file_manager.ensure_directory('delete_dir')
    file_manager.write_text('delete_dir/inner.txt', 'Inner file')
    base_dir = os.path.join(temp_root_dir, 'data')
    assert os.path.exists(os.path.join(base_dir, 'delete_me.txt'))
    assert os.path.exists(os.path.join(base_dir, 'delete_dir'))
    assert os.path.exists(os.path.join(base_dir, 'delete_dir', 'inner.txt'))
    file_manager.delete_file('delete_me.txt')
    assert not os.path.exists(os.path.join(base_dir, 'delete_me.txt'))
    file_manager.delete_file('delete_dir')
    assert not os.path.exists(os.path.join(base_dir, 'delete_dir'))
    with pytest.raises(FileError):
        file_manager.delete_file('nonexistent.txt')
def test_copy_move_file(file_manager, temp_root_dir):
    test_content = 'File to copy and move'
    file_manager.write_text('source.txt', test_content)
    base_dir = os.path.join(temp_root_dir, 'data')
    file_manager.copy_file('source.txt', 'dest.txt')
    assert os.path.exists(os.path.join(base_dir, 'source.txt'))
    assert os.path.exists(os.path.join(base_dir, 'dest.txt'))
    content = file_manager.read_text('dest.txt')
    assert content == test_content
    file_manager.move_file('source.txt', 'moved.txt')
    assert not os.path.exists(os.path.join(base_dir, 'source.txt'))
    assert os.path.exists(os.path.join(base_dir, 'moved.txt'))
    content = file_manager.read_text('moved.txt')
    assert content == test_content
    with pytest.raises(FileError):
        file_manager.copy_file('moved.txt', 'dest.txt', overwrite=False)
    new_content = 'New content'
    file_manager.write_text('new_source.txt', new_content)
    file_manager.copy_file('new_source.txt', 'dest.txt', overwrite=True)
    content = file_manager.read_text('dest.txt')
    assert content == new_content
def test_create_backup(file_manager, temp_root_dir):
    test_content = 'File to backup'
    file_manager.write_text('backup_me.txt', test_content)
    backup_path = file_manager.create_backup('backup_me.txt')
    backup_dir = os.path.join(temp_root_dir, 'data', 'backups')
    assert os.path.exists(os.path.join(backup_dir, backup_path))
    backup_content = file_manager.read_text(backup_path, 'backup')
    assert backup_content == test_content
def test_get_file_info(file_manager, temp_root_dir):
    test_content = 'Test file'
    file_manager.write_text('info_test.txt', test_content)
    file_info = file_manager.get_file_info('info_test.txt')
    assert file_info.name == 'info_test.txt'
    assert file_info.size == len(test_content)
    assert not file_info.is_directory
    assert file_info.file_type == FileType.TEXT
    dir_path = file_manager.ensure_directory('info_dir')
    dir_info = file_manager.get_file_info('info_dir')
    assert dir_info.name == 'info_dir'
    assert dir_info.is_directory
def test_file_manager_status(file_manager):
    status = file_manager.status()
    assert status['name'] == 'FileManager'
    assert status['initialized'] is True
    assert 'directories' in status
    assert 'disk_usage' in status
    assert 'active_locks' in status