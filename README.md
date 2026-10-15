<p align="center">
  <img src="docs/images/logo.png" width="200" alt="BLE AMPI">
</p>

<h1 align="center">BLE AMPI</h1>
<p align="center"><b>ADV Multi Purpose Integration</b> per Home Assistant</p>

<p align="center">
  <a href="https://github.com/LabirintoDigitale/ble-ampi/releases/"><img src="https://img.shields.io/github/v/release/LabirintoDigitale/ble-ampi.svg" alt="Release"></a>
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg" alt="HACS"></a>
</p>

> **BLE ADV Fan** è un'integrazione di [LabirintoDigitale](https://github.com/LabirintoDigitale) basata su [NicoIIT/ha-ble-adv](https://github.com/NicoIIT/ha-ble-adv) (licenza MIT, grazie a NicoIIT).

## Cos'è

Molti dispositivi economici non si "collegano" via Bluetooth: il telecomando o l'app **trasmettono il comando nell'aria** (BLE Advertising, "ADV") e il dispositivo lo ascolta, come un telecomando a infrarossi ma via radio. È il caso di ventilatori da soffitto, lampade, plafoniere, strisce LED, mattoncini luminosi, prese e tanto altro.

**BLE AMPI** porta tutti questi dispositivi in Home Assistant: non solo i ventilatori, ma **qualsiasi dispositivo comandato via BLE Advertising**. Riconosce i protocolli che conosce, impara i comandi di quelli che non conosce e ti permette di sperimentare con quelli nuovi.

| | Cosa puoi fare |
|---|---|
| 🌀 **Ventilatori e lampade** | Ventilatori da soffitto, plafoniere e lampade di decine di marche, con velocità, direzione, luci bianche e RGB |
| 🧱 **Mattoncino luci LEGO Kaiyu** | Le 12 uscite LED del controller compatibile LEGO come 12 luci indipendenti, con effetto lampeggio |
| 🎮 **Telecomando universale BLE** | Impara i tasti di qualsiasi telecomando o app BLE ADV e li trasforma in pulsanti ed eventi di Home Assistant |
| 📡 **Dispositivi Bluetooth presenti** | L'elenco dei dispositivi Bluetooth intorno a te presenti da almeno un'ora |
| 🧪 **Strumenti per sperimentare** | Ascolto e decodifica dei pacchetti, invio di pacchetti grezzi e di comandi di prova |

## 🌀 Ventilatori da soffitto e lampade

Il cuore dell'integrazione originale: controlla i dispositivi che usano i protocolli di queste app (Android e quasi sempre iOS):

* [LampSmart Pro](https://play.google.com/store/apps/details?id=com.jingyuan.lamp), [FanLamp Pro](https://play.google.com/store/apps/details?id=com.jingyuan.fan_lamp), [ApplianceSmart](https://play.google.com/store/apps/details?id=com.jingyuan.smart_home), [Vmax smart](https://play.google.com/store/apps/details?id=com.jingyuan.vmax_smart)
* [Zhi Jia](https://play.google.com/store/apps/details?id=com.cxw.cxwblelight), [Zhi Guang](https://play.google.com/store/apps/details?id=com.cxw.zhiguang), [Zhi Mei Deng Kong](http://mihuan.iotworkshop.com/zhiguang/)
* [Mantra Lighting](https://play.google.com/store/apps/details?id=com.newenergy.baolilan), [Smart Light / Argrace Smart](https://apkpure.com/argrace-smart/ai.argrace.oem), [LE Light Pro / 乐智光Pro](https://openapi.lelight.top/dl/cqan)
* [RuiXin](https://rx-etech.com/rxzn.html), [RW.LIGHT](https://play.google.com/store/apps/details?id=com.rw.rwblelight), [Smart Elfin](https://play.google.com/store/apps/details?id=com.warpfuture.wfiot.g), [GMIMA](https://www.jasonghost.com/lampSmartGmima/), [SmartHomeLight](https://wosk.top/zd.html)
* [Dudugu](https://app.dudugu.com/duduguapp/app/) (solo ventilatori), [eWeLink](https://play.google.com/store/apps/details?id=com.coolkit) (solo i dispositivi BLE ADV), [Hxlight](https://play.google.com/store/apps/details?id=com.dxc.delight) / [LED-Spots](https://play.google.com/store/apps/details?id=com.hmwin.bt.broadcast)
* e molti telecomandi fisici che usano gli stessi protocolli.

**Come si aggiunge:** Aggiungi integrazione → **BLE AMPI** → **Copia la configurazione dell'app già abbinata** (premi un tasto nell'app o sul telecomando e l'integrazione lo riconosce) oppure **Abbinamento**. Poi scegli le entità da creare: luci (bianco caldo/freddo, RGB, on/off) e ventilatori (3, 4, 6, 8 o 100 velocità, direzione, oscillazione, modalità notte e vento naturale).

> 💡 Se a volte la luce non si spegne, attiva **"Comandi inviati sempre, anche se lo stato non cambia"** per *Spegni* nella configurazione della luce (Riconfigura → Configura luci / ventilatori).

## 🧱 Mattoncino luci LEGO Kaiyu (12 uscite)

Il controller luci compatibile LEGO **Kaiyu** (12 uscite LED in 3 file da 4, alimentato dal box batterie o via USB, app "Kaiyu") diventa in Home Assistant:

* **12 luci**, "Linea 1" … "Linea 12", una per uscita, accendibili e spegnibili in modo **indipendente**;
* una luce **"Tutte le linee"**;
* l'effetto **Lampeggio** (veloce, eseguito dal controller) oltre a **Fisso**;
* lo stato segue anche i comandi dell'app Kaiyu.

**Come si aggiunge:** Aggiungi integrazione → **BLE AMPI** → **Controller luci LEGO Kaiyu (12 uscite)**, poi accendi o spegni una luce dall'app Kaiyu entro 15 secondi: il controller viene riconosciuto da solo.

> ⚠️ Tieni **chiusa l'app Kaiyu** quando usi Home Assistant: mentre è aperta ritrasmette di continuo il suo stato e sovrascrive i comandi.

Il protocollo è stato decodificato per questa integrazione: sbiancamento BLE dei mattoncini Mould King (port di [MouldKingCrypt](https://github.com/J0EK3R/mkconnect-python), MIT) più la codifica dell'app, con lo stato di tutte le 12 uscite in ogni comando. Luminosità ed effetti del pulsante fisico del controller non passano via Bluetooth.

## 🎮 Telecomando universale BLE

Impara i tasti di **qualsiasi** telecomando o app BLE Advertising, anche se il suo protocollo non è supportato:

1. Aggiungi integrazione → **BLE AMPI** → **Telecomando universale BLE**, dai un nome e scegli gli adattatori.
2. Per ogni tasto: dai un nome, premi **Invia**, **non premere nulla per 3 secondi** (analisi del rumore di fondo), poi premi più volte il tasto sul telecomando.
3. Scegli il segnale catturato (di solito il primo), verifica che il dispositivo reagisca e salva.

Ogni tasto diventa un **pulsante** di Home Assistant, e l'entità evento **"Tasto ricevuto"** scatta quando usi il telecomando originale. Il segnale viene trasmesso in un'unica trasmissione continua; ripetizioni e intervallo si regolano in **Parametri di trasmissione**.

> Non funziona con i dispositivi che richiedono una connessione Bluetooth (GATT). I telecomandi con codice variabile (rolling code) possono rifiutare un segnale ripetuto.

## 📡 Dispositivi Bluetooth presenti da almeno 1 ora

In **Aggiungi integrazione → BLE AMPI → Strumenti → Dispositivi Bluetooth presenti da almeno 1 ora** trovi i dispositivi Bluetooth presenti da più di un'ora che continuano a mandare un segnale ogni tanto: MAC, nome, RSSI, da quanto sono presenti, ultimo segnale, numero di segnali e adattatore che li ha ricevuti. Un dispositivo silenzioso per più di un'ora è considerato andato via. I dati arrivano dagli adattatori BLE ADV e dall'integrazione Bluetooth di Home Assistant.

## 🧪 Strumenti per sperimentare

* **Strumenti → Ascolta BLE ADV**: mostra per 10 secondi i pacchetti ricevuti, già decodificati quando il protocollo è noto.
* **Strumenti → Dump diagnostico**: scarica i pacchetti ricevuti e lo stato dell'integrazione.
* Servizio **`ble_adv_fan.inject_raw`**: trasmette un pacchetto grezzo.
* Servizio **`ble_adv_fan.send_command`**: manda a un dispositivo un comando (comando, parametro, argomenti) con il suo protocollo e il suo ID; accetta valori variabili, per provare comandi sconosciuti da uno script.

## Requisiti

Home Assistant deve poter trasmettere BLE Advertising con almeno uno di questi:

* un **adattatore Bluetooth** collegato direttamente all'host (Home Assistant OS su Linux, senza macchina virtuale in mezzo);
* uno o più proxy **ESPHome [ble_adv_proxy](https://github.com/NicoIIT/esphome-ble_adv_proxy)** (un normale `bluetooth_proxy` si estende facilmente);
* uno o più **Shelly** con proxy Bluetooth (firmware 2.0.0 o successivo, modalità scanner attiva).

Il dispositivo deve essere raggiungibile dal Bluetooth dell'adattatore o del proxy.

## Installazione

Tramite [HACS](https://www.hacs.xyz/):

[![Apri il repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=LabirintoDigitale&repository=ble-ampi)

HACS → ⋮ → Repository personalizzati → `https://github.com/LabirintoDigitale/ble-ampi` (categoria Integrazione) → Scarica → riavvia Home Assistant → Aggiungi integrazione **BLE AMPI**.

## Crediti

* [NicoIIT/ha-ble-adv](https://github.com/NicoIIT/ha-ble-adv): l'integrazione originale e tutti i protocolli di ventilatori e lampade (MIT).
* [J0EK3R/mkconnect-python](https://github.com/J0EK3R/mkconnect-python): lo sbiancamento BLE dei mattoncini Mould King (MIT).
* [LabirintoDigitale](https://github.com/LabirintoDigitale): telecomando universale, controller LEGO Kaiyu, dispositivi presenti, strumenti.

Licenza [MIT](LICENSE).
