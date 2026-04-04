import pytest
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
import chroma_client
import chromadb

@pytest.fixture(autouse=True)
def cleanup_clients():
    """Reset the global _CLIENTS dictionary before and after each test."""
    chroma_client._CLIENTS = {}
    yield
    chroma_client._CLIENTS = {}

def test_get_client_caching(tmp_path):
    """Test that get_client returns the same client instance for the same path."""
    db_path = str(tmp_path / "test_db")
    
    mock_client = MagicMock()
    with patch("chromadb.PersistentClient", return_value=mock_client):
        client1 = chroma_client.get_client(db_path)
        client2 = chroma_client.get_client(db_path)
        
        assert client1 is client2
        assert len(chroma_client._CLIENTS) == 1
        assert db_path in chroma_client._CLIENTS

def test_get_client_creates_directory(tmp_path):
    """Test that the database directory is created if it does not exist."""
    db_path = tmp_path / "new_db_dir"
    assert not db_path.exists()
    
    mock_client = MagicMock()
    with patch("chromadb.PersistentClient", return_value=mock_client):
        chroma_client.get_client(str(db_path))
        assert db_path.is_dir()

def test_get_client_calls_heartbeat(tmp_path):
    """Test that heartbeat is called to verify the connection."""
    db_path = str(tmp_path / "heartbeat_db")
    
    mock_client = MagicMock()
    with patch("chromadb.PersistentClient", return_value=mock_client):
        chroma_client.get_client(db_path)
        mock_client.heartbeat.assert_called_once()

def test_get_client_raises_runtime_error_on_failure(tmp_path):
    """Test that a RuntimeError is raised if Chroma client creation fails."""
    db_path = str(tmp_path / "fail_db")
    
    # Mocking ChromaError dynamically to avoid import issues if any
    with patch("chromadb.PersistentClient") as mock_create:
        mock_create.side_effect = chromadb.errors.ChromaError("Connection failed")
        
        with pytest.raises(RuntimeError) as exc_info:
            chroma_client.get_client(db_path)
        
        assert "Failed to create Chroma client" in str(exc_info.value)
