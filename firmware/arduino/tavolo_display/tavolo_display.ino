/**
 * RistoBAR - Arduino E-Ink Display
 * 
 * Display stato tavolo via WiFi (ESP-01S)
 * Hardware: Arduino UNO + ESP-01S + display e-paper 2.9"
 * 
 * Wiring:
 * - Arduino D10 -> ESP-01 RX
 * - Arduino D11 -> ESP-01 TX
 * - ESP-01 VCC -> 3.3V
 * - ESP-01 GND -> GND
 * 
 * Display: come configurazione ESP32
 */

#include <SoftwareSerial.h>
#include <ArduinoJson.h>

// Pin ESP-01 (SoftwareSerial)
#define ESP_RX 10
#define ESP_TX 11
SoftwareSerial espSerial(ESP_RX, ESP_TX);

// ============ CONFIGURAZIONE ============
const char* WIFI_SSID = "TUO_WIFI_SSID";
const char* WIFI_PASS = "TUO_WIFI_PASSWORD";

const char* SERVER = "192.168.1.100";
const int PORT = 8000;

const char* SALA_ID = "1";
const char* TAVOLO_NUM = "1";

// ============ STATO ============
String currentStato = "";

void setup() {
    Serial.begin(115200);
    espSerial.begin(9600);
    
    delay(1000);
    Serial.println("RistoBAR Arduino E-Ink");
    
    // Configura ESP-01 come station
    sendCommand("AT+RST", 2000);
    sendCommand("AT+CWMODE=1", 1000);
    
    // Connetti WiFi
    String cmd = "AT+CWJAP=\"" + String(WIFI_SSID) + "\",\"" + String(WIFI_PASS) + "\"";
    sendCommand(cmd.c_str(), 5000);
    
    Serial.println("WiFi connesso, fetching data...");
    fetchAndDisplay();
}

void loop() {
    // Ogni 60 secondi
    delay(60000);
    fetchAndDisplay();
}

// ============ ESP-01 COMANDI ============
String sendCommand(const char* cmd, int timeout) {
    Serial.println(cmd);
    espSerial.println(cmd);
    String response = "";
    long start = millis();
    while (millis() - start < timeout) {
        while (espSerial.available()) {
            char c = espSerial.read();
            response += c;
            Serial.write(c);
        }
    }
    return response;
}

// ============ FETCH ============
void fetchAndDisplay() {
    String cmd = "AT+HTTPCLIENT=1,1,\"http://" + String(SERVER) + ":" + String(PORT) + 
                 "/api/esp32/tavolo/" + String(SALA_ID) + "/" + String(TAVOLO_NUM) + 
                 "/\",\"\",\"\"";
    
    String response = sendCommand(cmd.c_str(), 10000);
    
    // Parse JSON (il response è tra "..." e ")
    int start = response.indexOf("{");
    int end = response.lastIndexOf("}");
    if (start > 0 && end > start) {
        String json = response.substring(start, end + 1);
        parseAndDisplay(json);
    } else {
        Serial.println("JSON non trovato");
    }
}

// ============ PARSE ============
void parseAndDisplay(String json) {
    StaticJsonDocument<512> doc;
    DeserializationError error = deserializeJson(doc, json);
    
    if (error) {
        Serial.print("Parse error: ");
        Serial.println(error.c_str());
        return;
    }
    
    String stato = doc["stato_testo"] | "?";
    
    if (stato == currentStato) {
        Serial.println("Nessun cambiamento");
        return;
    }
    currentStato = stato;
    
    Serial.print("Nuovo stato: ");
    Serial.println(stato);
    
    // Qui va il codice per aggiornare l'e-paper
    // (usa la stessa logica del firmware ESP32)
    updateEink(stato.c_str());
}

// ============ E-INK UPDATE ============
void updateEink(const char* stato) {
    // Placeholder - implementa con la tua libreria e-paper
    Serial.print("Aggiorno display: ");
    Serial.println(stato);
}