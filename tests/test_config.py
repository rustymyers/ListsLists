from app.config import Settings


def build_settings() -> Settings:
    return Settings(_env_file=None)


def test_empty_trusted_proxy_cidrs_env_value_is_an_empty_list(monkeypatch):
    monkeypatch.setenv("LISTSLISTS_TRUSTED_PROXY_CIDRS", "")

    assert build_settings().trusted_proxy_cidrs == []


def test_trusted_proxy_cidrs_env_value_accepts_comma_separated_networks(monkeypatch):
    monkeypatch.setenv(
        "LISTSLISTS_TRUSTED_PROXY_CIDRS",
        "172.20.0.0/16, 10.0.0.0/8",
    )

    assert build_settings().trusted_proxy_cidrs == ["172.20.0.0/16", "10.0.0.0/8"]
