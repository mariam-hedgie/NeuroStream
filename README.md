# NeuroStream  
**Real-Time Neural Signal Simulation, Quality Monitoring, and Incident Logging System**

NeuroStream is a prototype system that simulates multichannel neural data acquisition, performs real-time signal quality analysis, and logs signal degradation incidents with timestamps and diagnoses.

This project demonstrates core software concepts used in neural interface and medical monitoring systems, including continuous data streaming, signal quality assessment, and event logging.

---

## Table of Contents
1. Purpose and Motivation  
2. System Architecture  
3. Workflow Overview  
4. Signal Quality Metrics  
5. Status Definitions  
6. Incident Logging and Diagnosis  
7. User Interface  
8. How to Run  
9. Example Outputs  
10. Future Work  

---

## 1. Purpose and Motivation

NeuroStream provides a simplified but realistic prototype of a neural monitoring software pipeline.  
Its goal is to model how neural signals can be streamed, evaluated for quality, and automatically logged when problems occur.

The system focuses on:
- Explainable signal quality metrics  
- Transparent detection logic  
- Persistent incident logging  
- Modular and extensible design  

---

## 2. System Architecture

```
[ Simulator Thread ]
        |
        v
[ SQLite Database ] <---- Quality Monitor Thread
        |
        v
[ Flask REST API ]
        |
        v
[ Web Dashboard (Chart.js) ]
```

### Components

- **Simulator (`simulator.py`)**
  - Generates multichannel neural samples
  - Injects artifacts (dropout, noise, spikes, clipping)
  - Writes samples to database

- **Database (`db.py`)**
  - Stores neural samples
  - Stores detected signal incidents

- **Quality Analysis (`quality.py`)**
  - Computes RMS, dropout fraction, line noise ratio, and peak-to-peak
  - Assigns status and reasons

- **Flask API (`app.py`)**
  - Serves `/latest`, `/quality`, `/events`, `/control`
  - Runs monitoring thread
  - Exports logs

- **Frontend**
  - Real-time plot
  - Quality badges
  - Incident log table

---

## 3. Workflow Overview

1. Simulator generates samples  
2. Samples stored in database  
3. Quality monitor analyzes recent samples  
4. Incidents detected and logged  
5. Frontend displays signals and events  

---

## 4. Signal Quality Metrics

### RMS (Root Mean Square)
Measures signal power. Low RMS may indicate disconnected or flat channels.

### Peak-to-Peak Amplitude
Difference between max and min values. High values suggest spikes or clipping.

### Dropout Fraction
Percentage of zero or missing samples. Indicates packet loss or disconnection.

### Line Noise Ratio
Power near 60 Hz divided by total power. Indicates electrical interference.

---

## 5. Status Definitions

### Good
Normal RMS, low dropout, low line noise.

### Degraded
Moderate signal issues (early warning state).

### Bad
Severe signal failure. Signal unusable.

---

## 6. Incident Logging and Diagnosis

When a channel becomes degraded or bad, an incident is opened with:
- Start time
- Channel
- Status
- Reasons
- Diagnosis

When recovered:
- End time and duration are recorded

Example diagnoses:
- channel_dropout_severe  
- mains_interference_severe  
- flatline electrode  
- clipping/saturation  

---

## 7. User Interface

- Live signal plot  
- Quality tab with channel badges  
- Incidents tab with log table  
- Export to JSON/CSV  

---

## 8. How to Run

### Requirements
- Python 3.9+
- Flask, NumPy

### Install
```bash
pip install flask numpy
```

### Run
```bash
python app.py
```

### Open browser
```
http://127.0.0.1:5000
```

---

## 9. Example Outputs

### Live Signal Plot
![Live Signal Plot](docs/signal_plot.png)

### Incident Log
![Incident Log](docs/incidents_log.png)

---

## 10. Future Work

Future extensions may include:
- Real hardware integration  
- WebSocket streaming  
- Advanced filtering  
- Machine learning classifiers  
- Alerts and notifications  
- Cloud database backend  

---

## Educational Value

This project demonstrates:
- Real-time data pipelines  
- Signal quality engineering  
- REST APIs  
- Frontend-backend integration  
- Persistent event logging  

---

## Author
Mariam Husain  
Biomedical Engineering & Computer Science  
Johns Hopkins University  

