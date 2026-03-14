# Hackanova 5.0 - The Three Hackeeters 🚀

Welcome to our submission for **HACKANOVA 5.0**! 

**Team Name:** The Three Hackeeters

## 📌 Project Overview
Our project is an intelligent, real-time health monitoring and escalation system. It processes vital signs in real-time, leverages Machine Learning for anomaly detection, and utilizes LLMs (Gemini) for advanced reasoning to determine health risks and trigger automated escalations (like EMS notifications or doctor appointments).

## ✨ Key Features
- **Real-Time Signal Processing:** Ingests and processes continuous patient vitals.
- **ML Anomaly Detection:** Uses Isolation Forests to detect anomalous health patterns.
- **LLM-Powered Reasoning:** Integrates with Gemini API to provide contextual medical reasoning based on vitals and history.
- **Automated Escalation Engine:** Triggers alerts, EMS fall protocols, and doctor appointments based on risk scoring.
- **Interactive Dashboard:** A React-based frontend for monitoring patients and system alerts.

## 🛠️ Tech Stack
- **Backend:** Python, FastAPI, WebSockets, Pytest
- **Frontend:** React, Node.js, pnpm (Asset-Manager sandbox)
- **AI / ML:** Google Gemini API, Scikit-Learn (Isolation Forest)
- **Caching & State:** Redis
- **Data & APIs:** custom mock data generators and doctor fetching services

## 🚀 How to Run

### 1. Backend Setup
1. Navigate to the `backend` directory:
   ```bash
   cd backend
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables (copy `.env.example` to `.env` and fill in API keys).
4. Run the development server (make sure you have Redis running if needed):
   ```bash
   ./run_server.bat
   # or manually:
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
5. You can run the backend tests with:
   ```bash
   ./run_tests.bat
   ```

### 2. Frontend Setup
1. Navigate to the frontend workspace:
   ```bash
   cd frontend/Asset-Manager/artifacts/mockup-sandbox
   ```
2. Install dependencies using `pnpm`:
   ```bash
   pnpm install
   ```
3. Start the development server:
   ```bash
   npm run dev
   ```

### 3. Data Generation (Optional)
To generate the dataset or fetch doctor information:
```bash
cd data
python generate_dataset.py
```

## 🤝 The Team
- **The Three Hackeeters** 
*(Hackanova 5.0 Submission)*
