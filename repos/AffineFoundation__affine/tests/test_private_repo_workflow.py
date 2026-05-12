"""
Tests for Private HuggingFace Repo Workflow (Issue #248)

Tests the PrivateRepoWorkflow class which enables miners to deploy from
private HuggingFace repos to prevent model copying before on-chain commit.
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch

# Add project root to path for import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock the problematic imports before importing the module
sys.modules['affinetes'] = MagicMock()
sys.modules['affine.core.environments'] = MagicMock()
sys.modules['affine.utils.api_client'] = MagicMock()
sys.modules['affine.core.setup'] = MagicMock()
sys.modules['affine.core.setup'].logger = MagicMock()
sys.modules['affine.core.setup'].NETUID = 1
sys.modules['affine.utils.subtensor'] = MagicMock()

from affine.src.miner.commands import PrivateRepoWorkflow


class TestPrivateRepoWorkflowInit:
    """Test PrivateRepoWorkflow initialization."""
    
    def test_init_with_valid_tokens(self):
        """Should initialize with valid tokens."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        assert workflow.hf_token == "hf_test_token"
        assert workflow.chutes_api_key == "chutes_test_key"
        assert workflow._hf_api is None  # Lazy loaded
    
    def test_lazy_load_hf_api(self):
        """Should lazy-load HfApi on first access."""
        with patch('huggingface_hub.HfApi') as mock_hf_api:
            mock_hf_api.return_value = MagicMock()
            workflow = PrivateRepoWorkflow(
                hf_token="hf_test_token",
                chutes_api_key="chutes_test_key"
            )
            
            # First access should create the API
            _ = workflow.hf_api
            mock_hf_api.assert_called_once_with(token="hf_test_token")
            
            # Second access should reuse
            _ = workflow.hf_api
            mock_hf_api.assert_called_once()


class TestCreatePrivateRepo:
    """Test private HuggingFace repo creation."""
    
    def test_create_private_repo_success(self):
        """Should successfully create private repo."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        workflow._hf_api = MagicMock()
        workflow._hf_api.create_repo.return_value = None
        
        result = workflow.create_private_repo("user/model-name")
        
        assert result is True
        workflow._hf_api.create_repo.assert_called_once_with(
            repo_id="user/model-name",
            exist_ok=True,
            repo_type="model",
            private=True
        )
    
    def test_create_private_repo_failure(self):
        """Should return False on failure."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        workflow._hf_api = MagicMock()
        workflow._hf_api.create_repo.side_effect = Exception("API Error")
        
        result = workflow.create_private_repo("user/model-name")
        
        assert result is False


class TestUploadToRepo:
    """Test model upload to HuggingFace repo."""
    
    def test_upload_success(self):
        """Should return revision SHA on successful upload."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        workflow._hf_api = MagicMock()
        
        mock_info = MagicMock()
        mock_info.sha = "abc123def456789"
        workflow._hf_api.repo_info.return_value = mock_info
        
        result = workflow.upload_to_repo(
            repo_id="user/model",
            folder_path="/path/to/model",
            commit_message="Test upload"
        )
        
        assert result == "abc123def456789"
        workflow._hf_api.upload_folder.assert_called_once()
    
    def test_upload_failure(self):
        """Should return None on upload failure."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        workflow._hf_api = MagicMock()
        workflow._hf_api.upload_folder.side_effect = Exception("Upload failed")
        
        result = workflow.upload_to_repo(
            repo_id="user/model",
            folder_path="/path/to/model"
        )
        
        assert result is None


class TestUpdateVisibility:
    """Test HuggingFace repo visibility updates."""
    
    def test_make_public_success(self):
        """Should successfully make repo public."""
        with patch('huggingface_hub.update_repo_settings') as mock_update:
            workflow = PrivateRepoWorkflow(
                hf_token="hf_test_token",
                chutes_api_key="chutes_test_key"
            )
            
            result = workflow.make_public("user/model")
            
            assert result is True
            mock_update.assert_called_once_with(
                repo_id="user/model",
                private=False,
                token="hf_test_token"
            )
    
    def test_make_public_failure(self):
        """Should return False on visibility update failure."""
        with patch('huggingface_hub.update_repo_settings') as mock_update:
            mock_update.side_effect = Exception("Permission denied")
            
            workflow = PrivateRepoWorkflow(
                hf_token="hf_test_token",
                chutes_api_key="chutes_test_key"
            )
            
            result = workflow.make_public("user/model")
            
            assert result is False


class TestExecutePrivateUpload:
    """Test the complete private upload workflow."""
    
    @pytest.mark.asyncio
    async def test_execute_private_upload_success(self):
        """Should execute full private upload workflow."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        
        with patch.object(workflow, 'create_private_repo', return_value=True):
            with patch.object(workflow, 'upload_to_repo', return_value="abc123"):
                with patch.object(workflow, 'setup_private_repo_for_chutes', new_callable=AsyncMock, return_value=True):
                    result = await workflow.execute_private_upload(
                        repo_id="user/model",
                        folder_path="/path/to/model",
                        commit_message="Test upload"
                    )
                    
                    assert result == "abc123"
    
    @pytest.mark.asyncio
    async def test_execute_private_upload_repo_creation_fails(self):
        """Should return None if repo creation fails."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        
        with patch.object(workflow, 'create_private_repo', return_value=False):
            result = await workflow.execute_private_upload(
                repo_id="user/model",
                folder_path="/path/to/model"
            )
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_execute_private_upload_continues_on_secret_failure(self):
        """Should continue even if secret creation fails (with warning)."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        
        with patch.object(workflow, 'create_private_repo', return_value=True):
            with patch.object(workflow, 'upload_to_repo', return_value="abc123"):
                with patch.object(workflow, 'setup_private_repo_for_chutes', new_callable=AsyncMock, return_value=False):
                    result = await workflow.execute_private_upload(
                        repo_id="user/model",
                        folder_path="/path/to/model"
                    )
                    
                    # Should still return revision even if secret fails
                    assert result == "abc123"


class TestFinalizeAfterCommit:
    """Test finalization after on-chain commit."""
    
    @pytest.mark.asyncio
    async def test_finalize_success(self):
        """Should make repo public after commit."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        
        with patch.object(workflow, 'make_public', return_value=True):
            result = await workflow.finalize_after_commit("user/model")
            
            assert result is True
            workflow.make_public.assert_called_once_with("user/model")
    
    @pytest.mark.asyncio
    async def test_finalize_failure(self):
        """Should return False if making public fails."""
        workflow = PrivateRepoWorkflow(
            hf_token="hf_test_token",
            chutes_api_key="chutes_test_key"
        )
        
        with patch.object(workflow, 'make_public', return_value=False):
            result = await workflow.finalize_after_commit("user/model")
            
            assert result is False


class TestConstants:
    """Test class constants."""
    
    def test_api_base_url(self):
        """Should have correct Chutes API base URL."""
        assert PrivateRepoWorkflow.CHUTES_API_BASE == "https://api.chutes.ai"
    
    def test_secret_key_name(self):
        """Should use HF_TOKEN as secret key."""
        assert PrivateRepoWorkflow.SECRET_KEY_HF_TOKEN == "HF_TOKEN"
