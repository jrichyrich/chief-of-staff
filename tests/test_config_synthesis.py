def test_dispatch_synthesis_config_defaults():
    import config as app_config
    assert hasattr(app_config, "DISPATCH_SYNTHESIS_ENABLED")
    assert app_config.DISPATCH_SYNTHESIS_ENABLED is False
    assert hasattr(app_config, "DISPATCH_SYNTHESIS_MODEL")
    assert app_config.DISPATCH_SYNTHESIS_MODEL == "claude-haiku-4-5-20251001"
    assert hasattr(app_config, "DISPATCH_SYNTHESIS_MAX_TOKENS")
    assert app_config.DISPATCH_SYNTHESIS_MAX_TOKENS == 1024
