# tests/modules/conftest.py
import pytest
from unittest.mock import Mock

# Фикстуры
@pytest.fixture
def mock_logger():
    logger = Mock()
    logger.dbg = Mock()
    logger.inf = Mock()
    logger.wrn = Mock()
    logger.err = Mock()
    logger.crt = Mock()
    return logger