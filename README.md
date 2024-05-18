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

