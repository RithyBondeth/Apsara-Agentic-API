# Apsara Agentic API

A professional FastAPI project with a modular, production-ready structure.

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   uvicorn app.main:app --reload
   ```

3. **Explore API Documentation**:
   - Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
   - ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Project Structure

```text
app/
├── api/
│   └── v1/
│       ├── api.py
│       └── endpoints/
│           └── health.py
├── core/
│   └── config.py
└── main.py
.env
.gitignore
requirements.txt
```
