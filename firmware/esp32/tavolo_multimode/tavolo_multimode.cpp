/**
 * RistoBAR - ESP32 Multi-Mode E-Ink Display
 * 
 * Display stato tavolo con supporto WiFi, BLE o entrambi
 * Hardware: ESP32 + display e-paper Waveshare 2.9"
 * 
 * MODALITA' CONFIGURABILI:
 * - MODE_WIFI_ONLY: Solo WiFi, fetch periodico dal server
 * - MODE_BLE_ONLY: Solo BLE, riceve dati da server/bridge
 * - MODE_COMBINED: WiFi + BLE, entrambi attivi
 */

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>

// ============ MODALITA' ============
#define MODE_WIFI_ONLY   0
#define MODE_BLE_ONLY    1
#define MODE_COMBINED    2

// ============ CONFIGURAZIONE ============
struct Config {
    int modalita = MODE_WIFI_ONLY;  // 0=WiFi, 1=BLE, 2=Combinato
    char ssid[32] = "";
    char password[64] = "";
    char server[64] = "192.168.1.100";
    int porta = 8000;
    int sala_id = 1;
    int tavolo_num = 1;
    int refresh_sec = 60;
    char ble_name[32] = "RistoBAR";
};

Config config;
Preferences prefs;

// ============ DISPLAY ============
#include <GxEPD2_BW.h>
#include <Fonts/FreeMonoBold12pt.h>
#include <Fonts/FreeMonoBold24pt.h>

#define EINK_CS    15
#define EINK_DC    4
#define EINK_RST   2
#define EINK_BUSY  16

GxEPD2_BW<GxEPD2_290, GxEPD2_290::_HEIGHT> display(GxEPD2_290(EINK_CS, EINK_DC, EINK_RST, EINK_BUSY));

// ============ STATO ============
String currentStato = "";
bool hasWifi = false;
bool hasBLE = false;
bool newBleData = false;
String bleData = "";

// BLE
BLEServer *server = nullptr;
bool deviceConnected = false;

// Timer
unsigned long lastFetch = 0;

class ServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) { deviceConnected = true; Serial.println("BLE: Connesso"); }
    void onDisconnect(BLEServer* pServer) { deviceConnected = false; Serial.println("BLE: Disconnesso"); }
};

class ConfigCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
        std::string val = pCharacteristic->getValue();
        if (val.length() > 0) {
            parseConfigCommand(String(val.c_str()));
        }
    }
};

void setup() {
    Serial.begin(115200);
    delay(500);
    
    // Display init
    display.init(115200);
    display.setFont(&FreeMonoBold12pt);
    display.setRotation(1);
    
    // Carica configurazione
    loadConfig();
    
    showSplash();
    
    // Init in base alla modalità
    if (config.modalita == MODE_WIFI_ONLY || config.modalita == MODE_COMBINED) {
        initWiFi();
    }
    
    if (config.modalita == MODE_BLE_ONLY || config.modalita == MODE_COMBINED) {
        initBLE();
    }
    
    showReady();
}

void loop() {
    unsigned long now = millis();
    
    // WiFi fetch
    if (config.modalita == MODE_WIFI_ONLY || config.modalita == MODE_COMBINED) {
        if (hasWifi && (now - lastFetch > config.refresh_sec * 1000)) {
            fetchFromWiFi();
            lastFetch = now;
        }
    }
    
    // Process BLE data
    if (newBleData) {
        newBleData = false;
        processData(bleData);
    }
    
    delay(100);
}

// ============ WIFI ============
void initWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(config.ssid, config.password);
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        hasWifi = true;
        Serial.println("\nWiFi OK");
        fetchFromWiFi();
    } else {
        Serial.println("\nWiFi FAIL");
    }
}

void fetchFromWiFi() {
    if (!hasWifi) return;
    
    HTTPClient http;
    char url[128];
    sprintf(url, "http://%s:%d/api/esp32/tavolo/%d/%d/", 
             config.server, config.porta, config.sala_id, config.tavolo_num);
    
    Serial.println(url);
    http.begin(url);
    http.setTimeout(5000);
    
    if (http.GET() == 200) {
        String payload = http.getString();
        processData(payload);
    }
    http.end();
}

// ============ BLE ============
void initBLE() {
    BLEDevice::init(config.ble_name);
    server = BLEDevice::createServer();
    server->setServerCallbacks(new ServerCallbacks());
    
    BLEService *svc = server->createService("6e400001-b5a3-f393-e0a9-e50e24dcca9e");
    
    // Characteristic per dati
    BLECharacteristic *dataChar = svc->createCharacteristic(
        "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_WRITE
    );
    dataChar->setCallbacks(new ConfigCallbacks());
    dataChar->addDescriptor(new BLE2902());
    
    // Characteristic per configurazione
    BLECharacteristic *cfgChar = svc->createCharacteristic(
        "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
        BLECharacteristic::PROPERTY_WRITE
    );
    cfgChar->setCallbacks(new ConfigCallbacks());
    cfgChar->addDescriptor(new BLE2902());
    
    svc->start();
    
    BLEAdvertising *adv = BLEDevice::getAdvertising();
    adv->addServiceUUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e");
    BLEDevice::startAdvertising();
    
    Serial.println("BLE started");
}

// ============ CONFIG ============
void loadConfig() {
    prefs.begin("ristobar");
    config.modalita = prefs.getInt("mode", MODE_WIFI_ONLY);
    prefs.getString("ssid", config.ssid, 32);
    prefs.getString("pass", config.password, 64);
    prefs.getString("server", config.server, 64);
    config.porta = prefs.getInt("port", 8000);
    config.sala_id = prefs.getInt("sala", 1);
    config.tavolo_num = prefs.getInt("tavolo", 1);
    config.refresh_sec = prefs.getInt("refresh", 60);
    prefs.getString("blename", config.ble_name, 32);
    prefs.end();
    
    Serial.printf("Config: mode=%d, ssid=%s, sala=%d, tavolo=%d\n",
                  config.modalita, config.ssid, config.sala_id, config.tavolo_num);
}

void parseConfigCommand(String cmd) {
    // Formato: SET:key=value;key=value
    if (cmd.startsWith("SET:")) {
        String pairs = cmd.substring(4);
        while (pairs.length() > 0) {
            int sep = pairs.indexOf('=');
            int end = pairs.indexOf(';');
            if (end < 0) end = pairs.length();
            
            if (sep > 0) {
                String key = pairs.substring(0, sep);
                String val = pairs.substring(sep + 1, end);
                applyConfig(key, val);
            }
            
            if (end >= pairs.length()) break;
            pairs = pairs.substring(end + 1);
        }
        
        // Salva e riavvia
        saveConfig();
        showSaved();
    }
    
    // Richiesta configurazione
    if (cmd == "GET") {
        String cfg = "MODE:" + String(config.modalita) + ";";
        cfg += "SSID:" + String(config.ssid) + ";";
        cfg += "SERVER:" + String(config.server) + ";";
        cfg += "SALA:" + String(config.sala_id) + ";";
        cfg += "TAVOLO:" + String(config.tavolo_num);
        Serial.println(cfg);
    }
}

void applyConfig(String key, String val) {
    if (key == "mode") config.modalita = val.toInt();
    else if (key == "ssid") val.toCharArray(config.ssid, 32);
    else if (key == "pass") val.toCharArray(config.password, 64);
    else if (key == "server") val.toCharArray(config.server, 64);
    else if (key == "port") config.porta = val.toInt();
    else if (key == "sala") config.sala_id = val.toInt();
    else if (key == "tavolo") config.tavolo_num = val.toInt();
    else if (key == "refresh") config.refresh_sec = val.toInt();
    else if (key == "blename") val.toCharArray(config.ble_name, 32);
}

void saveConfig() {
    prefs.begin("ristobar");
    prefs.putInt("mode", config.modalita);
    prefs.putString("ssid", config.ssid);
    prefs.putString("pass", config.password);
    prefs.putString("server", config.server);
    prefs.putInt("port", config.porta);
    prefs.putInt("sala", config.sala_id);
    prefs.putInt("tavolo", config.tavolo_num);
    prefs.putInt("refresh", config.refresh_sec);
    prefs.putString("blename", config.ble_name);
    prefs.end();
}

// ============ PROCESS DATA ============
void processData(String json) {
    String stato = "";
    String nome = "";
    int posti = 0;
    bool hasOrder = false;
    
    // Parse JSON (formato compresso o completo)
    if (json.indexOf("\"s\":\"") > 0) {
        int s = json.indexOf("\"s\":\"");
        int e = json.indexOf("\"", s + 5);
        stato = json.substring(s + 5, e);
    } else if (json.indexOf("\"stato_testo\":\"") > 0) {
        int s = json.indexOf("\"stato_testo\":\"");
        int e = json.indexOf("\"", s + 15);
        stato = json.substring(s + 15, e);
    }
    
    if (json.indexOf("\"n\":\"") > 0) {
        int s = json.indexOf("\"n\":\"");
        int e = json.indexOf("\"", s + 5);
        nome = json.substring(s + 5, e);
    }
    
    // Mappa stato
    if (stato == "L") stato = "LIBERO";
    else if (stato == "P") stato = "PRENOTATO";
    else if (stato == "O") stato = "OCCUPATO";
    else if (stato == "C") stato = "CONTO";
    
    if (stato == currentStato && nome == currentNome) {
        Serial.println("No change");
        return;
    }
    
    currentStato = stato;
    currentNome = nome;
    updateDisplay(stato.c_str(), nome.c_str(), posti, hasOrder);
}

// ============ DISPLAY ============
void updateDisplay(const char* stato, const char* nome, int posti, bool hasOrder) {
    display.fillScreen(GxEPD_WHITE);
    
    display.setFont(&FreeMonoBold24pt);
    display.setCursor(10, 28);
    display.print("Tavolo ");
    display.println(config.tavolo_num);
    
    // Indicatore modalità
    display.setFont(&FreeMonoBold12pt);
    display.setCursor(10, 50);
    if (config.modalita == MODE_WIFI_ONLY) display.print("[WiFi]");
    else if (config.modalita == MODE_BLE_ONLY) display.print("[BLE]");
    else display.print("[WiFi+BLE]");
    
    display.setCursor(80, 50);
    display.print(stato);
    
    if (strlen(nome) > 0) {
        display.setCursor(10, 75);
        display.print("Prenotato: ");
        display.println(nome);
    }
    
    if (hasOrder) {
        display.setCursor(10, 100);
        display.println("*** ORDINE ATTIVO ***");
    }
    
    display.display();
}

// ============ UI ============
void showSplash() {
    display.fillScreen(GxEPD_WHITE);
    display.setFont(&FreeMonoBold12pt);
    display.setCursor(20, 60);
    display.println("RistoBAR");
    display.setCursor(20, 80);
    display.println("Init...");
    display.display();
}

void showReady() {
    display.fillScreen(GxEPD_WHITE);
    display.setFont(&FreeMonoBold12pt);
    display.setCursor(10, 40);
    display.println("RistoBAR Multi");
    display.setCursor(10, 60);
    display.print("Tavolo: ");
    display.println(config.tavolo_num);
    display.setCursor(10, 80);
    if (config.modalita == MODE_WIFI_ONLY) display.println("Mode: WiFi");
    else if (config.modalita == MODE_BLE_ONLY) display.println("Mode: BLE");
    else display.println("Mode: Combined");
    display.setCursor(10, 100);
    display.print("Sala: ");
    display.println(config.sala_id);
    display.display();
}

void showSaved() {
    display.fillScreen(GxEPD_WHITE);
    display.setFont(&FreeMonoBold12pt);
    display.setCursor(20, 60);
    display.println("Config salvata!");
    display.display();
    delay(2000);
    showReady();
}