# API using FastAPI, 
- this is my dev / uat for any API development and testing platform; hosted at DG, 

### features
* API integration with FAST API
* 

### view docs using endpoint/docs
```gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app```
```gunicorn -w 2 -k uvicorn.workers.UvicornWorker app.main:app```
#### local test run caommand
```uvicorn app.main:app --reload```
```uvicorn --host 0.0.0.0  app.main:app --reload```

## 9Jul2024##
`uvicorn app.main:app --host 0.0.0.0 --port 8080`

## Oct14 2024 
`uvicorn --host 0.0.0.0 app.main:app --workers 4`


### ngrok for test
```
ngrok http port
```

```
pip freeze > requirements.txt
```
```
4 dec 2024 test vercel
```