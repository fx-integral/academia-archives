import pytest
import aiohttp
from datetime import (
    datetime,
    timedelta,
)
from unittest.mock import (
    Mock,
    patch,
    AsyncMock,
)


@pytest.fixture
def mock_config_data():
    return {
        "defaultWaitTime": 1000,
        "expirationTimeMinutes": 60,
        "sites": {
            "forever21": {
                "baseUrl": "https://www.forever21.com",
                "productUrl": "https://www.forever21.com/us/2001361088.html",
                "actions": [
                    {
                        "name": "closePopup",
                        "selectors": [
                            "//*[@id='globale_popup']/div/div/div/div[1]/span"
                        ],
                        "type": "click",
                        "waitAfter": 2000,
                    }
                ],
                "cartUrl": "https://www.forever21.com/us/shop/checkout/basket",
                "promoCode": {
                    "inputSelector": "//*[@id='couponCode']",
                    "invalidSelector": "//*[@id='cartCouponInvalidFeedback']",
                    "validSelector": "//*[@id='cartCouponValidFeedback']",
                    "applySelector": "//*[@id='main']/div[3]/div[2]/div[2]/div[2]/div/div[2]/div[2]/div/div[1]/form/div/div[2]/button",
                },
            }
        },
    }


@pytest.fixture
def config_provider():
    return ConfigProvider(
        api_url="http://test-api.com/config",
        cache_file="test_config_cache",
    )


@pytest.mark.asyncio
async def test_fetch_config_from_api(
    config_provider,
    mock_config_data,
):
    # Create mock response
    mock_response = AsyncMock()
    mock_response.__aenter__.return_value.json.return_value = mock_config_data
    mock_response.__aenter__.return_value.raise_for_status = Mock()

    with patch(
        "aiohttp.ClientSession.get",
        return_value=mock_response,
    ):
        config = await config_provider._fetch_config_from_api()

        assert isinstance(
            config,
            Config,
        )
        assert config.defaultWaitTime == 1000
        assert config.expirationTimeMinutes == 60
        assert "forever21" in config.sites
        assert isinstance(
            config.sites["forever21"],
            SiteConfig,
        )


@pytest.mark.asyncio
async def test_fetch_config_from_api_error(
    config_provider,
):
    mock_response = AsyncMock()
    mock_response.__aenter__.side_effect = aiohttp.ClientError()

    with patch(
        "aiohttp.ClientSession.get",
        return_value=mock_response,
    ):
        with pytest.raises(Exception):
            await config_provider._fetch_config_from_api()


def test_get_cached_config(
    config_provider,
    mock_config_data,
):
    mock_config = Config.model_validate(mock_config_data)
    mock_config.expirationDate = datetime.now() + timedelta(minutes=30)

    with patch("shelve.open") as mock_shelve:
        mock_db = {}
        mock_db[config_provider.cache_key] = mock_config
        mock_shelve.return_value.__enter__.return_value = mock_db

        cached_config = config_provider._get_cached_config()
        assert cached_config == mock_config


def test_get_cached_config_expired(
    config_provider,
    mock_config_data,
):
    mock_config = Config.model_validate(mock_config_data)
    mock_config.expirationDate = datetime.now() - timedelta(minutes=1)

    with patch("shelve.open") as mock_shelve:
        mock_db = {}
        mock_db[config_provider.cache_key] = mock_config
        mock_shelve.return_value.__enter__.return_value = mock_db

        cached_config = config_provider._get_cached_config()
        assert cached_config is None


def test_cache_config(
    config_provider,
    mock_config_data,
):
    mock_config = Config.model_validate(mock_config_data)

    with patch("shelve.open") as mock_shelve:
        mock_db = {}
        mock_shelve.return_value.__enter__.return_value = mock_db

        config_provider._cache_config(mock_config)
        assert mock_db[config_provider.cache_key] == mock_config
        assert mock_config.expirationDate is not None


@pytest.mark.asyncio
async def test_get_config_from_cache(
    config_provider,
    mock_config_data,
):
    mock_config = Config.model_validate(mock_config_data)
    mock_config.expirationDate = datetime.now() + timedelta(minutes=30)

    with patch.object(
        config_provider,
        "_get_cached_config",
        return_value=mock_config,
    ):
        config = await config_provider.get_config()
        assert config == mock_config


@pytest.mark.asyncio
async def test_get_config_from_api(
    config_provider,
    mock_config_data,
):
    # Create mock response
    mock_response = AsyncMock()
    mock_response.__aenter__.return_value.json.return_value = mock_config_data
    mock_response.__aenter__.return_value.raise_for_status = Mock()

    with (
        patch("shelve.open") as mock_shelve,
        patch(
            "aiohttp.ClientSession.get",
            return_value=mock_response,
        ),
    ):
        # Mock empty cache
        mock_db = {}
        mock_shelve.return_value.__enter__.return_value = mock_db

        config = await config_provider.get_config()

        # Verify the config was properly fetched and cached
        assert isinstance(
            config,
            Config,
        )
        assert config.defaultWaitTime == 1000
        assert config.expirationTimeMinutes == 60
        assert "forever21" in config.sites
        assert isinstance(
            config.sites["forever21"],
            SiteConfig,
        )
        assert config.expirationDate is not None
