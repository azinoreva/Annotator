"""
FastAPI app for the annotator.

Run with:  uvicorn app:app --reload
"""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException

import crud
import schemas

from db import register_tortoise


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with register_tortoise(app):
        # DB connection is open for the whole yield block; closed on exit.
        yield


app = FastAPI(title="Annotator API", lifespan=lifespan)


# ---------------------------------------------------------------------------
# unsent_annotations
# ---------------------------------------------------------------------------

@app.post("/unsent-annotations", response_model=schemas.UnsentAnnotationOut, status_code=201)
async def create_unsent_annotation(payload: schemas.UnsentAnnotationIn):
    return await crud.add_unsent_annotation(**payload.model_dump())


@app.get("/unsent-annotations/{update_id}", response_model=schemas.UnsentAnnotationOut)
async def read_unsent_annotation(update_id: str):
    obj = await crud.get_unsent_annotation(update_id)
    if obj is None:
        raise HTTPException(404, "unsent annotation not found")
    return obj


@app.get("/unsent-annotations", response_model=list[schemas.UnsentAnnotationOut])
async def list_unsent_annotations(user_id: Optional[str] = None, category: Optional[str] = None):
    filters = {k: v for k, v in {"user_id": user_id, "category": category}.items() if v is not None}
    return await crud.list_unsent_annotations(**filters)


@app.delete("/unsent-annotations/{update_id}", status_code=204)
async def delete_unsent_annotation(update_id: str):
    if not await crud.delete_unsent_annotation(update_id):
        raise HTTPException(404, "unsent annotation not found")


# ---------------------------------------------------------------------------
# received_annotations
# ---------------------------------------------------------------------------

@app.post("/received-annotations", response_model=schemas.ReceivedAnnotationOut, status_code=201)
async def create_received_annotation(payload: schemas.ReceivedAnnotationIn):
    return await crud.add_received_annotation(**payload.model_dump())


@app.get("/received-annotations/{update_id}", response_model=schemas.ReceivedAnnotationOut)
async def read_received_annotation(update_id: str):
    obj = await crud.get_received_annotation(update_id)
    if obj is None:
        raise HTTPException(404, "received annotation not found")
    return obj


@app.get("/received-annotations", response_model=list[schemas.ReceivedAnnotationOut])
async def list_received_annotations(user_id: Optional[str] = None, category: Optional[str] = None):
    filters = {k: v for k, v in {"user_id": user_id, "category": category}.items() if v is not None}
    return await crud.list_received_annotations(**filters)


@app.delete("/received-annotations/{update_id}", status_code=204)
async def delete_received_annotation(update_id: str):
    if not await crud.delete_received_annotation(update_id):
        raise HTTPException(404, "received annotation not found")


# ---------------------------------------------------------------------------
# processed_annotations
# ---------------------------------------------------------------------------

@app.post("/processed-annotations", response_model=schemas.ProcessedAnnotationOut, status_code=201)
async def create_processed_annotation(payload: schemas.ProcessedAnnotationIn):
    return await crud.add_processed_annotation(**payload.model_dump())


@app.get("/processed-annotations/{update_id}", response_model=schemas.ProcessedAnnotationOut)
async def read_processed_annotation(update_id: str):
    obj = await crud.get_processed_annotation(update_id)
    if obj is None:
        raise HTTPException(404, "processed annotation not found")
    return obj


@app.get("/processed-annotations", response_model=list[schemas.ProcessedAnnotationOut])
async def list_processed_annotations(user_id: Optional[str] = None, category: Optional[str] = None):
    filters = {k: v for k, v in {"user_id": user_id, "category": category}.items() if v is not None}
    return await crud.list_processed_annotations(**filters)


@app.delete("/processed-annotations/{update_id}", status_code=204)
async def delete_processed_annotation(update_id: str):
    if not await crud.delete_processed_annotation(update_id):
        raise HTTPException(404, "processed annotation not found")


# ---------------------------------------------------------------------------
# sent_annotations
# ---------------------------------------------------------------------------

@app.post("/sent-annotations", response_model=schemas.SentAnnotationOut, status_code=201)
async def create_sent_annotation(payload: schemas.SentAnnotationIn):
    return await crud.add_sent_annotation(**payload.model_dump())


@app.get("/sent-annotations/{update_id}", response_model=schemas.SentAnnotationOut)
async def read_sent_annotation(update_id: str):
    obj = await crud.get_sent_annotation(update_id)
    if obj is None:
        raise HTTPException(404, "sent annotation not found")
    return obj


@app.get("/sent-annotations", response_model=list[schemas.SentAnnotationOut])
async def list_sent_annotations(user_id: Optional[str] = None, category: Optional[str] = None):
    filters = {k: v for k, v in {"user_id": user_id, "category": category}.items() if v is not None}
    return await crud.list_sent_annotations(**filters)


@app.delete("/sent-annotations/{update_id}", status_code=204)
async def delete_sent_annotation(update_id: str):
    if not await crud.delete_sent_annotation(update_id):
        raise HTTPException(404, "sent annotation not found")


# ---------------------------------------------------------------------------
# analysis  (composite key: category_name + today, both in the path)
# ---------------------------------------------------------------------------

@app.put("/analysis/{category_name}/{today}", response_model=schemas.AnalysisOut)
async def upsert_analysis(category_name: str, today: str, payload: schemas.AnalysisIn):
    return await crud.upsert_analysis(category_name, today, payload.frequency)


@app.get("/analysis/{category_name}/{today}", response_model=schemas.AnalysisOut)
async def read_analysis(category_name: str, today: str):
    obj = await crud.get_analysis(category_name, today)
    if obj is None:
        raise HTTPException(404, "analysis not found")
    return obj


@app.get("/analysis", response_model=list[schemas.AnalysisOut])
async def list_analysis(category_name: Optional[str] = None, today: Optional[str] = None):
    filters = {k: v for k, v in {"category_name": category_name, "today": today}.items() if v is not None}
    return await crud.list_analysis(**filters)


@app.delete("/analysis/{category_name}/{today}", status_code=204)
async def delete_analysis(category_name: str, today: str):
    if not await crud.delete_analysis(category_name, today):
        raise HTTPException(404, "analysis not found")