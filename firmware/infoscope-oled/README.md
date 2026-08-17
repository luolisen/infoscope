# Infoscope OLED firmware (Phase A1)

This isolated ESP32 firmware subscribes to retained Event snapshots at `infoscope/display/events/v1` and displays the newest three titles.

1. Install Arduino ESP32 core and the `U8g2` and `MQTT` libraries.
2. Copy `infoscope_oled/wifi_config.example.h` to `infoscope_oled/wifi_config.h`; do not commit it.
3. Run `./upload.sh` (or supply another serial port as its first argument).

Defaults: generic ESP32 FQBN `esp32:esp32:esp32`, SSD1306 128×64 OLED, SDA GPIO 21, SCL GPIO 22. For SH1106, replace the U8g2 constructor before compiling.

Before Phase A2 (the independent status topic and pixel sprite), verify Chinese rendering, three-line display, scroll animation, and retained-message recovery after restart.
