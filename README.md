# API using FastAPI, 
- this is my dev / uat for any API development and testing platform; hosted at DG, 

### features
* API integration with FAST API
* 

### view docs using endpoint/docs
```gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app```

#### local test run caommand
```uvicorn app.main:app --reload```
```uvicorn --host 0.0.0.0  app.main:app --reload```


### ngrok for test
```
ngrok http port
```

```
pip freeze > requirements.txt
```

# API Documentation

This document provides information about the APIs in our application.

## Umami API - `/api/v1/umami`
...
## AGI API - `/api/v1/agi`
... 
## CDN API - `/api/v1/cdn`
...cloudflare API integration incliude R2, images and Streaming
## Dev API - `/api/v1/dev`
...as develop idea, quick test
## Agents API - `/api/v1/agents`
...chat completion using openAI API and whisper API
## Auth API - `/api/v1/auth`
...jwt token auth
## Chat API - `/api/v1`
... 
## CV API - `/api/v1/cv`
...my personal website content
## RAG API - `/api/v1/rag`
...multimodel without using langchain
## Text Detect API - `/api/v1/textdetect`
... ongoing develop a A.I detect / humanize writing A.P.I for users