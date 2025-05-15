# Multivio API

Backend API for Multivio application.

## Project Structure

```
.
├── app                # Application code
│   ├── models         # Pydantic models
│   ├── routers        # API endpoints
│   ├── services       # Business logic
│   ├── static         # Static files
│   ├── templates      # Template files
│   └── utils          # Utility functions
├── main.py            # FastAPI application entry point
└── requirements.txt   # Project dependencies
```

## Getting Started

### Prerequisites

- Python 3.9+
- pip

### Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd agdoc
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the application:
   ```bash
   python main.py
   ```

The API will be available at http://localhost:8000.

## API Documentation

Once the application is running, you can access the API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
