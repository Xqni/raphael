"""Agent loop skeleton.
Continuously pulls queued jobs, plans, executes tools, and records narration.
For this wave we implement a very simple loop that marks jobs as running then done.
"""
import asyncio
from .jobs import store as job_store

async def process_job(job):
    job_id = job['id']
    # Mark running
    job_store.update_status(job_id, 'running')
    # Placeholder: pretend work with async sleep
    await asyncio.sleep(0.1)
    # Mark done
    job_store.update_status(job_id, 'done', result='completed')

async def loop_once():
    jobs = [j for j in job_store.list_jobs() if j['status'] == 'queued']
    tasks = [process_job(j) for j in jobs]
    if tasks:
        await asyncio.gather(*tasks)

async def main_loop(stop_event: asyncio.Event):
    while not stop_event.is_set():
        await loop_once()
        await asyncio.sleep(0.5)
