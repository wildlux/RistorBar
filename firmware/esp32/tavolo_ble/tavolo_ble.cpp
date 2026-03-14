/**
 * RistoBAR - ESP32 BLE E-Ink Display
 * 
 * Display stato tavolo via Bluetooth Low Energy
 * Hardware: ESP32 + display e-paper Waveshare 2.9"
 * 
 * Modalità: BLE Peripheral - riceve dati dal server/Django via BLE
 * 
 * UUIDs custom per il servizio:
 * - Service: 0xFFF0
 * - Characteristic: 0xFFF1 (notify)
 */

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <WiFi.h>

// ============ CONFIGURAZIONE BLE ============
#define SERVICE_UUID        "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define CHARACTERISTIC_UUID "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

// Nome del dispositivo BLE
const char* BLE_NAME = "RistoBAR-Tavolo";

// ============ CONFIGURAZIONE WiFi (per debug OTA) ============
const char* SSID = "TUO_WIFI_SSID";
const char* PASSWORD = "TUO_WIFI_PASSWORD";

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
String currentNome = "";
bool hasOrder = false;

bool newData = false;
String bleData = "";

// BLE Server
BLEServer *server = nullptr;
BLEService *service = nullptr;
BLECharacteristic *characteristic = nullptr;
bool deviceConnected = false;

class ServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
        deviceConnected = true;
        Serial.println("BLE: Client connesso");
    }
    void onDisconnect(BLEServer* pServer) {
        deviceConnected = false;
        Serial.println("BLE: Client disconnesso");
    }
};

class CharacteristicCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
        std::string rxValue = pCharacteristic->getValue();
        if (rxValue.length() > 0) {
            bleData = String(rxValue.c_str());
            Serial.println("BLE: Dati ricevuti:");
            Serial.println(bleData);
            newData = true;
        }
    }
};

void setup() {
    Serial.begin(115200);
    
    // Init display
    display.init(115200);
    display.setFont(&FreeMonoBold12pt);
    display.setRotation(1);
    
    showSplash();
    
    // Init BLE
    initBLE();
    
    Serial.println("RistoBAR ESP32 BLE pronto!");
    showReady();
}

void loop() {
    if (newData) {
        newData = false;
        parseAndDisplay(bleData);
    }
    
    // Deep sleep mode - wakeup su timer (60s) o BLE activity
    delay(1000);
}

// ============ BLE INIT ============
void initBLE() {
    BLEDevice::init(BLE_NAME);
    server = BLEDevice::createServer();
    server->setServerCallbacks(new ServerCallbacks());
    
    service = server->createService(SERVICE_UUID);
    
    characteristic = service->createCharacteristic(
        CHARACTERISTIC_UUID,
        BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_WRITE
    );
    characteristic->setCallbacks(new CharacteristicCallbacks());
    characteristic->addDescriptor(new BLE2902());
    
    service->start();
    
    BLEAdvertising *advertising = BLEDevice::getAdvertising();
    advertising->addServiceUUID(SERVICE_UUID);
    advertising->setScanResponse(true);
    advertising->setMinPreferred(0x06);
    advertising->setMinPreferred(0x12);
    
    BLEDevice::startAdvertising();
    Serial.println("BLE: Servizio avviato, in attesa di connessioni...");
}

// ============ PARSE ============
void parseAndDisplay(String json) {
    // Supporta anche formato compresso STM32
    // {t:1, s:"L", n:"", p:0, h:""}
    // o formato completo ESP32
    
    String stato = "";
    String nome = "";
    int posti = 0;
    bool hasOrder = false;
    
    // Prova formato compresso
    if (json.startsWith("{")) {
        int sIdx = json.indexOf("\"s\":\"");
        int sEnd = json.indexOf("\"", sIdx + 5);
        if (sIdx > 0 && sEnd > sIdx) {
            stato = json.substring(sIdx + 5, sEnd);
        }
        
        int nIdx = json.indexOf("\"n\":\"");
        int nEnd = json.indexOf("\"", nIdx + 5);
        if (nIdx > 0 && nEnd > nIdx) {
            nome = json.substring(nIdx + 5, nEnd);
        }
        
        int pIdx = json.indexOf("\"p\":");
        if (pIdx > 0) {
            String pVal = json.substring(pIdx + 4);
            posti = pVal.toInt();
        }
        
        // Formato completo
        int stIdx = json.indexOf("\"stato_testo\":\"");
        if (stIdx > 0) {
            int stEnd = json.indexOf("\"", stIdx + 16);
            stato = json.substring(stIdx + 15, stEnd);
        }
        
        int nomIdx = json.indexOf("\"nome\":\"");
        if (nomIdx > 0) {
            int nomEnd = json.indexOf("\"", nomIdx + 8);
            nome = json.substring(nomIdx + 8, nomEnd);
        }
    }
    
    // Mappa stato
    String statoTesto = stato;
    if (stato == "L") statoTesto = "LIBERO";
    else if (stato == "P") statoTesto = "PRENOTATO";
    else if (stato == "O") statoTesto = "OCCUPATO";
    else if (stato == "C") statoTesto = "CONTO";
    
    // Aggiorna solo se cambiato
    if (statoTesto == currentStato && nome == currentNome) {
        Serial.println("Nessun cambiamento");
        return;
    }
    
    currentStato = statoTesto;
    currentNome = nome;
    
    updateDisplay(statoTesto.c_str(), nome.c_str(), posti, hasOrder);
}

// ============ DISPLAY ============
void updateDisplay(const char* stato, const char* nome, int posti, bool hasOrder) {
    display.fillScreen(GxEPD_WHITE);
    
    display.setFont(&FreeMonoBold24pt);
    display.setCursor(10, 30);
    display.println("Tavolo (BLE)");
    
    display.setFont(&FreeMonoBold12pt);
    display.setCursor(10, 55);
    display.print("Stato: ");
    display.println(stato);
    
    if (strlen(nome) > 0) {
        display.setCursor(10, 80);
        display.print("Prenotato: ");
        display.println(nome);
        
        display.print("Posti: ");
        display.println(posti);
    }
    
    if (hasOrder) {
        display.setCursor(10, 110);
        display.println("*** ORDINE ATTIVO ***");
    }
    
    display.display();
    Serial.println("Display aggiornato");
}

// ============ HELPERS ============
void showSplash() {
    display.fillScreen(GxEPD_WHITE);
    display.setFont(&FreeMonoBold12pt);
    display.setCursor(20, 60);
    display.println("RistoBAR BLE");
    display.display();
}

void showReady() {
    display.fillScreen(GxEPD_WHITE);
    display.setFont(&FreeMonoBold12pt);
    display.setCursor(10, 50);
    display.println("Pronto!");
    display.setCursor(10, 70);
    display.println("Connetti via BLE");
    display.setCursor(10, 90);
    display.println(BLE_NAME);
    display.display();
}