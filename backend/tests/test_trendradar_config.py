from pathlib import Path

import pytest

from infoscope.integrations.trendradar.config import load_trendradar_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_frozen_trendradar_sources_load_from_repository_config() -> None:
    config = load_trendradar_config(REPOSITORY_ROOT / "backend/config/trendradar.yaml")

    assert [source.id for source in config.newsnow.sources] == [
        "baidu",
        "weibo",
        "thepaper",
        "wallstreetcn-hot",
        "cls-hot",
        "zhihu",
        "bilibili-hot-search",
    ]
    assert [feed.id for feed in config.rss.feeds] == ["hacker-news"]


def test_config_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    path = tmp_path / "trendradar.yaml"
    path.write_text(
        """
newsnow:
  api_url: https://example.com/api/s
  timeout_seconds: 10
  max_retries: 0
  sources:
    - {id: duplicate, name: First, expected_domain: example.com}
    - {id: duplicate, name: Second, expected_domain: example.com}
rss:
  timeout_seconds: 10
  feeds: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate ids"):
        load_trendradar_config(path)


def test_config_rejects_remote_plain_http(tmp_path: Path) -> None:
    path = tmp_path / "trendradar.yaml"
    path.write_text(
        """
newsnow:
  api_url: http://example.com/api/s
  timeout_seconds: 10
  max_retries: 0
  sources: []
rss:
  timeout_seconds: 10
  feeds: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="HTTPS or local HTTP"):
        load_trendradar_config(path)
