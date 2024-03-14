# API using FastAPI,

### view docs using endpoint/docs
```gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app```

#### local test run caommand
```uvicorn app.main:app --reload```