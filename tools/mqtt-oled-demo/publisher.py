"""Publish retained mock Infoscope event snapshots for the OLED demo."""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

import paho.mqtt.client as mqtt

TOPIC = "infoscope/display/events/v1"
MAX_EVENTS = 12
MAX_OLED_CHARS = 10

MOCK_EVENTS = [
    "SpaceX星舰完成新一轮测试", "英伟达发布新一代AI芯片", "美联储释放最新利率信号",
    "OpenAI公布新模型能力", "中国低空经济试点继续扩大", "全球半导体供应链出现新变化",
    "机器人产业迎来新一轮融资", "商业航天发射计划密集推进", "新能源电池价格继续变化",
    "人工智能开源生态持续扩张",
]


def oled_title(title: str, *, max_chars: int = MAX_OLED_CHARS) -> str:
    """Normalize whitespace and truncate only the display representation."""
    normalized = " ".join(title.split())
    return normalized if len(normalized) <= max_chars else normalized[: max_chars - 2] + ".."


def encode_snapshot(revision: str, titles: Sequence[str]) -> str:
    """Encode at most 12 titles, ordered from oldest to newest."""
    return "\n".join(["IS-EVENTS/1", revision, *(oled_title(title) for title in titles[-MAX_EVENTS:])])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="infoscope-mock-publisher")
    client.connect(args.host, args.port, 60)
    client.loop_start()
    events, next_index = MOCK_EVENTS[:3], 3
    try:
        while True:
            published = client.publish(TOPIC, payload=encode_snapshot(str(time.time_ns()), events).encode("utf-8"), qos=1, retain=True)
            published.wait_for_publish()
            print("\n已发布：", *(f"\n  {title}" for title in events[-3:]))
            time.sleep(args.interval)
            events = [*events, MOCK_EVENTS[next_index]][-MAX_EVENTS:]
            next_index = (next_index + 1) % len(MOCK_EVENTS)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
