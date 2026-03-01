def test_proactive_action_config_defaults():
    import config as app_config
    assert hasattr(app_config, "PROACTIVE_ACTION_ENABLED")
    assert app_config.PROACTIVE_ACTION_ENABLED is False
    assert hasattr(app_config, "PROACTIVE_ACTION_CATEGORIES")
    assert "checkpoint" in app_config.PROACTIVE_ACTION_CATEGORIES
    assert "delegation" in app_config.PROACTIVE_ACTION_CATEGORIES
