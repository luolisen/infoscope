#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <MQTT.h>
#include <U8g2lib.h>
#include "wifi_config.h"

#define MQTT_PORT 1883
#define MQTT_TOPIC "infoscope/display/events/v1"
#define OLED_SDA 21
#define OLED_SCL 22
#define MAX_EVENTS 12
#define PAGE_SIZE 3

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
WiFiClient network;
MQTTClient mqtt(1024);
String eventTitles[MAX_EVENTS];
int eventCount = 0;
String lastRevision;
String pendingPayload;
bool pendingUpdate = false;
unsigned long lastMqttAttempt = 0;

bool readLine(const String &text, int &position, String &line) {
  if (position >= text.length()) return false;
  int newline = text.indexOf('\n', position);
  line = newline == -1 ? text.substring(position) : text.substring(position, newline);
  position = newline == -1 ? text.length() : newline + 1;
  line.replace("\r", "");
  return true;
}

void latestPage(String output[PAGE_SIZE]) {
  for (int i = 0; i < PAGE_SIZE; ++i) output[i] = "";
  int start = max(0, eventCount - PAGE_SIZE);
  for (int i = start; i < eventCount; ++i) output[i - start] = eventTitles[i];
}

void drawPage(String lines[PAGE_SIZE]) {
  const int baseline[] = {15, 35, 55};
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_wqy12_t_gb2312);
  for (int i = 0; i < PAGE_SIZE; ++i) if (lines[i].length()) u8g2.drawUTF8(0, baseline[i], lines[i].c_str());
  u8g2.sendBuffer();
}

void animatePage(String oldLines[PAGE_SIZE], String newLines[PAGE_SIZE]) {
  const int baseline[] = {15, 35, 55};
  for (int offset = 0; offset <= 64; offset += 8) {
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_wqy12_t_gb2312);
    for (int i = 0; i < PAGE_SIZE; ++i) {
      int oldY = baseline[i] - offset;
      int newY = baseline[i] + 64 - offset;
      if (oldLines[i].length() && oldY >= 0 && oldY <= 64) u8g2.drawUTF8(0, oldY, oldLines[i].c_str());
      if (newLines[i].length() && newY >= 0 && newY <= 64) u8g2.drawUTF8(0, newY, newLines[i].c_str());
    }
    u8g2.sendBuffer();
    delay(20);
  }
  drawPage(newLines);
}

void applySnapshot(const String &payload) {
  int position = 0;
  String protocol, revision;
  if (!readLine(payload, position, protocol) || protocol != "IS-EVENTS/1" || !readLine(payload, position, revision) || revision == lastRevision) return;
  String oldPage[PAGE_SIZE];
  latestPage(oldPage);
  String line;
  int count = 0;
  while (count < MAX_EVENTS && readLine(payload, position, line)) if (line.length()) eventTitles[count++] = line;
  eventCount = count;
  lastRevision = revision;
  String newPage[PAGE_SIZE];
  latestPage(newPage);
  bool firstSnapshot = !oldPage[0].length() && !oldPage[1].length() && !oldPage[2].length();
  if (firstSnapshot) drawPage(newPage); else animatePage(oldPage, newPage);
}

void messageReceived(String &topic, String &payload) {
  if (topic == MQTT_TOPIC) { pendingPayload = payload; pendingUpdate = true; }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) delay(500);
}

void connectMQTT() {
  if (mqtt.connected() || millis() - lastMqttAttempt < 2000) return;
  lastMqttAttempt = millis();
  String clientId = "infoscope-oled-" + WiFi.macAddress();
  clientId.replace(":", "");
  if (mqtt.connect(clientId.c_str())) mqtt.subscribe(MQTT_TOPIC, 1);
}

void setup() {
  Serial.begin(115200);
  Wire.begin(OLED_SDA, OLED_SCL);
  u8g2.begin();
  String loading[PAGE_SIZE] = {"观澜连接中", "", ""};
  drawPage(loading);
  connectWiFi();
  mqtt.begin(MQTT_HOST, MQTT_PORT, network);
  mqtt.onMessage(messageReceived);
  connectMQTT();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  mqtt.loop();
  connectMQTT();
  if (pendingUpdate) { String payload = pendingPayload; pendingUpdate = false; applySnapshot(payload); }
  delay(5);
}
