from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import AuthError
from app.modules.compute import service
from app.modules.compute.schemas import ClaimInput, HeartbeatInput, ResultInput

router = APIRouter(prefix="/internal/compute", tags=["compute"])
Database = Annotated[Session, Depends(get_db)]


def _authenticate(request, db):
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or " " in token:
        raise AuthError(401, "COMPUTE_UNAUTHENTICATED", "计算节点认证无效")
    return service.authenticate_worker(db, token, now=request.app.state.auth_clock)


@router.post("/claim")
def claim(data: ClaimInput, request: Request, db: Database):
    worker = _authenticate(request, db)
    job = service.claim(db, worker, now=request.app.state.auth_clock)
    db.commit()
    return {"job": job}


@router.post("/{job_id}/heartbeat", status_code=204)
def heartbeat(job_id: UUID, data: HeartbeatInput, request: Request, db: Database):
    worker = _authenticate(request, db)
    service.heartbeat(db, worker, job_id, data.lease_token, now=request.app.state.auth_clock)
    db.commit()
    return Response(status_code=204)


@router.post("/{job_id}/result", status_code=204)
def result(job_id: UUID, data: ResultInput, request: Request, db: Database):
    worker = _authenticate(request, db)
    service.submit_result(
        db,
        worker,
        job_id,
        data.lease_token,
        data.result.model_dump(mode="json"),
        now=request.app.state.auth_clock,
    )
    db.commit()
    return Response(status_code=204)
