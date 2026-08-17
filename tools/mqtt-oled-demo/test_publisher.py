from publisher import MAX_EVENTS, encode_snapshot, oled_title


def test_oled_title_normalizes_and_truncates() -> None:
    assert oled_title("  OpenAI   发布新模型 \n ") == "OpenAI 发.."


def test_snapshot_protocol_keeps_the_latest_twelve_oldest_to_newest() -> None:
    payload = encode_snapshot("123", [f"事件{i}" for i in range(14)])
    lines = payload.splitlines()
    assert lines[:2] == ["IS-EVENTS/1", "123"]
    assert lines[2:] == [f"事件{i}" for i in range(2, 14)]
    assert len(lines[2:]) == MAX_EVENTS
