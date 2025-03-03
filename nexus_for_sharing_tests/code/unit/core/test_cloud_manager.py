import os
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from nexus_core.core.cloud_manager import CloudManager, CloudProvider, StorageBackend
from nexus_core.utils.exceptions import ManagerInitializationError
@pytest.fixture
def temp_root_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)
@pytest.fixture
def cloud_config(temp_root_dir):
    base_dir = os.path.join(temp_root_dir, 'data')
    return {'provider': 'none', 'storage': {'enabled': True, 'type': 'local', 'base_directory': base_dir, 'bucket': 'test-bucket', 'prefix': 'test-prefix'}}
@pytest.fixture
def config_manager_mock(cloud_config):
    config_manager = MagicMock()
    config_manager.get.return_value = cloud_config
    return config_manager
@pytest.fixture
def cloud_manager(config_manager_mock, temp_root_dir):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    file_manager = MagicMock()
    cloud_mgr = CloudManager(config_manager_mock, logger_manager, file_manager)
    cloud_mgr.initialize()
    yield cloud_mgr
    cloud_mgr.shutdown()
def test_cloud_manager_initialization(config_manager_mock, temp_root_dir):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    file_manager = MagicMock()
    cloud_mgr = CloudManager(config_manager_mock, logger_manager, file_manager)
    cloud_mgr.initialize()
    assert cloud_mgr.initialized
    assert cloud_mgr.healthy
    assert cloud_mgr._provider == CloudProvider.NONE
    assert cloud_mgr._storage_backend == StorageBackend.LOCAL
    assert cloud_mgr._storage_service is not None
    cloud_mgr.shutdown()
    assert not cloud_mgr.initialized
def test_cloud_provider_validation(config_manager_mock):
    config_manager_mock.get.return_value = {'provider': 'invalid_provider', 'storage': {'enabled': False}}
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    cloud_mgr = CloudManager(config_manager_mock, logger_manager)
    cloud_mgr.initialize()
    assert cloud_mgr._provider == CloudProvider.NONE
    cloud_mgr.shutdown()
def test_storage_backend_validation(config_manager_mock):
    config_manager_mock.get.return_value = {'provider': 'none', 'storage': {'enabled': True, 'type': 'invalid_backend'}}
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    cloud_mgr = CloudManager(config_manager_mock, logger_manager)
    cloud_mgr.initialize()
    assert cloud_mgr._storage_backend == StorageBackend.LOCAL
    cloud_mgr.shutdown()
@patch('nexus_core.core.cloud_manager.LocalStorageService')
def test_local_storage_service(mock_local_storage, config_manager_mock, temp_root_dir):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    file_manager = MagicMock()
    cloud_mgr = CloudManager(config_manager_mock, logger_manager, file_manager)
    cloud_mgr.initialize()
    mock_local_storage.assert_called_once()
    mock_local_storage.return_value.initialize.assert_called_once()
    cloud_mgr.shutdown()
@patch('nexus_core.core.cloud_manager.AWSStorageService')
def test_aws_storage_service(mock_aws_storage, config_manager_mock):
    config_manager_mock.get.return_value = {'provider': 'aws', 'storage': {'enabled': True, 'type': 's3', 'bucket': 'test-bucket', 'prefix': 'test-prefix'}}
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    with patch('nexus_core.core.cloud_manager.boto3', MagicMock()):
        cloud_mgr = CloudManager(config_manager_mock, logger_manager)
        cloud_mgr.initialize()
        mock_aws_storage.assert_called_once()
        mock_aws_storage.return_value.initialize.assert_called_once()
        assert cloud_mgr._provider == CloudProvider.AWS
        assert cloud_mgr._storage_backend == StorageBackend.S3
        cloud_mgr.shutdown()
@patch('nexus_core.core.cloud_manager.AzureBlobStorageService')
def test_azure_storage_service(mock_azure_storage, config_manager_mock):
    config_manager_mock.get.return_value = {'provider': 'azure', 'storage': {'enabled': True, 'type': 'azure_blob', 'container': 'test-container', 'prefix': 'test-prefix'}}
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    cloud_mgr = CloudManager(config_manager_mock, logger_manager)
    with patch.dict('sys.modules', {'azure.storage.blob': MagicMock()}):
        cloud_mgr.initialize()
        mock_azure_storage.assert_called_once()
        mock_azure_storage.return_value.initialize.assert_called_once()
        assert cloud_mgr._provider == CloudProvider.AZURE
        assert cloud_mgr._storage_backend == StorageBackend.AZURE_BLOB
        cloud_mgr.shutdown()
@patch('nexus_core.core.cloud_manager.GCPStorageService')
def test_gcp_storage_service(mock_gcp_storage, config_manager_mock):
    config_manager_mock.get.return_value = {'provider': 'gcp', 'storage': {'enabled': True, 'type': 'gcp_storage', 'bucket': 'test-bucket', 'prefix': 'test-prefix'}}
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    cloud_mgr = CloudManager(config_manager_mock, logger_manager)
    with patch.dict('sys.modules', {'google.cloud': MagicMock()}):
        cloud_mgr.initialize()
        mock_gcp_storage.assert_called_once()
        mock_gcp_storage.return_value.initialize.assert_called_once()
        assert cloud_mgr._provider == CloudProvider.GCP
        assert cloud_mgr._storage_backend == StorageBackend.GCP_STORAGE
        cloud_mgr.shutdown()
def test_file_operations(cloud_manager, temp_root_dir):
    local_file_path = os.path.join(temp_root_dir, 'test_local.txt')
    with open(local_file_path, 'w') as f:
        f.write('Test content')
    cloud_manager._storage_service.upload_file.return_value = True
    cloud_manager._storage_service.download_file.return_value = True
    cloud_manager._storage_service.delete_file.return_value = True
    cloud_manager._storage_service.list_files.return_value = [{'name': 'file1.txt', 'path': 'file1.txt', 'size': 100}, {'name': 'file2.txt', 'path': 'file2.txt', 'size': 200}]
    result = cloud_manager.upload_file(local_file_path, 'remote/test.txt')
    assert result is True
    cloud_manager._storage_service.upload_file.assert_called_with(local_file_path, 'remote/test.txt')
    download_path = os.path.join(temp_root_dir, 'downloaded.txt')
    result = cloud_manager.download_file('remote/test.txt', download_path)
    assert result is True
    cloud_manager._storage_service.download_file.assert_called_with('remote/test.txt', download_path)
    result = cloud_manager.delete_file('remote/test.txt')
    assert result is True
    cloud_manager._storage_service.delete_file.assert_called_with('remote/test.txt')
    files = cloud_manager.list_files('remote/')
    assert len(files) == 2
    cloud_manager._storage_service.list_files.assert_called_with('remote/')
def test_provider_detection(cloud_manager):
    assert cloud_manager.is_cloud_provider('none') is True
    assert cloud_manager.is_cloud_provider('aws') is False
    assert cloud_manager.is_cloud_provider(CloudProvider.NONE) is True
    assert cloud_manager.is_cloud_provider(CloudProvider.AWS) is False
    assert cloud_manager.get_cloud_provider() == 'none'
    assert cloud_manager.get_storage_backend() == 'local'
def test_service_access(cloud_manager):
    service = cloud_manager.get_service('storage')
    assert service is not None
    assert service == cloud_manager._storage_service
    service = cloud_manager.get_service('nonexistent')
    assert service is None
def test_config_change_handling(cloud_manager):
    cloud_manager._on_config_changed('cloud.provider', 'aws')
    cloud_manager._logger.warning.assert_called_with('Configuration change to cloud.provider requires restart to take effect', extra={'key': 'cloud.provider'})
def test_cloud_manager_status(cloud_manager):
    cloud_manager._storage_service.status.return_value = {'initialized': True, 'base_directory': '/path/to/storage'}
    status = cloud_manager.status()
    assert status['name'] == 'CloudManager'
    assert status['initialized'] is True
    assert 'provider' in status
    assert 'storage' in status
    assert 'services' in status
    assert 'storage' in status['services']
def test_operations_without_initialization():
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    cloud_mgr = CloudManager(MagicMock(), logger_manager)
    with pytest.raises(ValueError, match='not initialized'):
        cloud_mgr.upload_file('local.txt', 'remote.txt')
    with pytest.raises(ValueError, match='not initialized'):
        cloud_mgr.download_file('remote.txt', 'local.txt')
    with pytest.raises(ValueError, match='not initialized'):
        cloud_mgr.list_files()
def test_cloud_manager_with_disabled_storage(config_manager_mock):
    config_manager_mock.get.return_value = {'provider': 'none', 'storage': {'enabled': False}}
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    cloud_mgr = CloudManager(config_manager_mock, logger_manager)
    cloud_mgr.initialize()
    assert cloud_mgr.initialized
    assert cloud_mgr._storage_service is None
    with pytest.raises(ValueError, match='not enabled'):
        cloud_mgr.upload_file('local.txt', 'remote.txt')
    cloud_mgr.shutdown()