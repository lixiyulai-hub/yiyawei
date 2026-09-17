from src.config import load_config


def test_default_auto_stop_silence_threshold_matches_product_default():
    config = load_config("config.yaml")
    no_paste_config = load_config("config.no_paste.yaml")

    assert config["recorder"]["auto_stop"]["silence_sec"] == 2.0
    assert no_paste_config["recorder"]["auto_stop"]["silence_sec"] == 2.0
    assert config["recorder"]["auto_stop"]["level_threshold"] == 0.015
    assert no_paste_config["recorder"]["auto_stop"]["level_threshold"] == 0.015
