"""FastAPI application for the Brain core.
Provides /health, /ws (placeholder), /jobs CRUD, and /control.
"""
import os
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict

from .jobs.store import create_job, get_job, list_jobs, update_status, cancel_job

app = FastAPI()

# Token handling — RAPHAEL_TOKEN_PATH lets tests point at a temp file so the
# REAL ~/.raphael/token is never written or deleted (the original test did).
def get_token():
    path = os.environ.get('RAPHAEL_TOKEN_PATH') or os.path.expanduser('~/.raphael/token')
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except Exception:
        return None

def token_auth(x_raphael_token: Optional[str] = Header(None)):
    # Missing header must be 401 (auth), not 422 (validation) — Header(...) is
    # required-param validation, which fires before this dependency.
    expected = get_token()
    if not expected or not x_raphael_token or x_raphael_token != expected:
        raise HTTPException(status_code=401, detail='Invalid token')
    return True

@app.get('/health')
def health(auth: bool = Depends(token_auth)):
    return {'status': 'ok'}

# WebSocket placeholder – actual implementation delegated to router-dev
@app.get('/ws')
def ws_placeholder():
    return JSONResponse(content={'detail': 'WebSocket endpoint is handled by router component'}, status_code=200)

# Jobs API
@app.get('/jobs')
def get_jobs(auth: bool = Depends(token_auth)) -> List[Dict]:
    return list_jobs()

class JobIn(BaseModel):
    task: str
    priority: int = 0

@app.post('/jobs')
def post_job(body: JobIn, auth: bool = Depends(token_auth)) -> Dict:
    job_id = create_job(body.task, body.priority)
    return {'job_id': job_id}

@app.get('/jobs/{job_id}')
def job_status(job_id: int, auth: bool = Depends(token_auth)) -> Dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return job

@app.post('/jobs/{job_id}/cancel')
def cancel(job_id: int, auth: bool = Depends(token_auth)) -> Dict:
    success = cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail='Cannot cancel')
    return {'cancelled': True}

# Control endpoint – placeholder for future commands
@app.post('/control')
def control(command: str, auth: bool = Depends(token_auth)):
    # In a full implementation this would route to internal control logic.
    return {'result': f'Command {command} received'}
