# Infoscope MQTT OLED demo

An isolated Phase A1 simulator. It does not import, modify, or connect to the Infoscope application or database.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
./run_broker.sh
```

In another terminal, inspect the retained snapshot:

```bash
mosquitto_sub -h 127.0.0.1 -t 'infoscope/display/events/v1' -v
```

Then run `./run_publisher.sh`. The payload is UTF-8, QoS 1, retained, and contains up to 12 titles ordered oldest to newest. Run `pytest -q` for protocol checks. Do not expose this anonymous broker to the public internet.
