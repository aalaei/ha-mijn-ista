"""Global pytest configuration — loads HA custom component test fixtures."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Tell HA's loader to also search custom_components/ in this repo."""
    return
