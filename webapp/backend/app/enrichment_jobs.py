"""In-memory bulk enrichment job state (single active job, mirrors rag_ingestor's progress pattern)."""

from __future__ import annotations

import threading
import uuid
from typing import Any

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_active_job_id: str | None = None


def start_job(total: int) -> str:
    global _active_job_id
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "phase": "running",
            "total": total,
            "done": 0,
            "failed": 0,
            "current_title": "",
            "errors": [],
        }
        _active_job_id = job_id
    return job_id


def update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(fields)


def record_item(job_id: str, *, ok: bool, title: str, error: str | None = None) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["current_title"] = title
        if ok:
            job["done"] += 1
        else:
            job["failed"] += 1
            if error:
                job["errors"].append({"title": title, "error": error})


def finish_job(job_id: str) -> None:
    global _active_job_id
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["phase"] = "complete"
        if _active_job_id == job_id:
            _active_job_id = None


def fail_job(job_id: str, message: str) -> None:
    global _active_job_id
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["phase"] = "error"
            job["message"] = message
        if _active_job_id == job_id:
            _active_job_id = None


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def active_job_id() -> str | None:
    with _lock:
        return _active_job_id
