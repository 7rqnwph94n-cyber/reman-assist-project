from config import ProductionConfig, TestingConfig


def test_test_selectors_default_in_testing():
    assert TestingConfig.ENABLE_TEST_SELECTORS is True


def test_test_selectors_disabled_in_production():
    assert ProductionConfig.ENABLE_TEST_SELECTORS is False
