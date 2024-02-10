# API using FastAPI,

### view docs using endpoint/docs
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app