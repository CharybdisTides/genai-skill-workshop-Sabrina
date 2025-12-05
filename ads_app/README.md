# Alaska's Department of Snow

A demo web application showcasing GenAI integration with Google Cloud. This project demonstrates how to build an LLM-powered chat interface deployed on Cloud Run with integrated Cloud Logging.

## Overview

- **Purpose**: Learning project - deployed on Cloud Run to demonstrate GenAI SDK integration with Google Cloud services
- **Backend**: Python with FastAPI
- **Frontend**: Svelte with responsive UI components
- **LLM**: Google GenAI SDK
- **Logging**: Cloud Logging (runs natively on Cloud Run)
- **Data**: BigQuery integration for conversation logging

## Architecture

```
┌─────────────────────────────────────────────┐
│         Frontend (Svelte)                   │
│  ┌─────────────────────────────────────┐   │
│  │  Entry Textbox                      │   │
│  │  History Log                        │   │
│  │  Snowy Mountain Banner              │   │
│  │  "Alaska Department of Snow"        │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
                    ↓ HTTP
┌─────────────────────────────────────────────┐
│      FastAPI Backend (Cloud Run)            │
│  ┌─────────────────────────────────────┐   │
│  │  /chat endpoint                     │   │
│  │  GenAI SDK Integration              │   │
│  │  Request Processing                 │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
         ↓              ↓              ↓
    GenAI API    Cloud Logging    BigQuery
```

## User Flow

1. User enters text in the frontend textbox
2. Frontend sends HTTP request to FastAPI backend
3. Backend processes request using GenAI SDK
4. LLM generates response
5. Conversation logged to Cloud Logging (automatic in Cloud Run environment)
6. Response sent back to frontend
7. Frontend updates history log and displays response

## Project Structure

```
ads_app/
├── README.md                 # This file
├── background/               # Backend services
│   ├── main.py              # FastAPI entry point
│   └── service/
│       └── llm_generate/     # GenAI integration module
├── frontend/                # Svelte frontend
│   ├── templates/           # HTML templates
│   └── static/              # Assets (CSS, JS)
└── pytest/                  # Unit tests
```

## Key Dependencies

- **FastAPI**: REST API framework
- **Google GenAI SDK**: LLM integration
- **Svelte**: Frontend framework
- **Cloud Logging**: Automatic in Cloud Run environment

## Development Notes

- This is a **demo/learning project** - no production hardening
- Unit tests located in `pytest/` directory
- Cloud Logging integration is automatic when deployed to Cloud Run (no manual configuration needed)
- BigQuery connection configured through Cloud Run service account permissions
