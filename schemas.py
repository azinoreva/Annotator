from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# unsent_annotations
# ---------------------------------------------------------------------------

class UnsentAnnotationIn(BaseModel):
    update_id: str
    datetime: int
    update_data: str
    category: str
    annotations: Any
    user_id: str


class UnsentAnnotationOut(UnsentAnnotationIn):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# received_annotations  (category is optional here, matching the schema)
# ---------------------------------------------------------------------------

class ReceivedAnnotationIn(BaseModel):
    update_id: str
    datetime: int
    update_data: str
    user_id: str
    category: Optional[str] = None


class ReceivedAnnotationOut(ReceivedAnnotationIn):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# processed_annotations
# ---------------------------------------------------------------------------

class ProcessedAnnotationIn(BaseModel):
    update_id: str
    datetime: int
    update_data: str
    category: str
    annotations: Any
    morality: Optional[Any] = None
    user_id: str


class ProcessedAnnotationOut(ProcessedAnnotationIn):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# sent_annotations
# ---------------------------------------------------------------------------

class SentAnnotationIn(BaseModel):
    update_id: str
    datetime: int
    update_data: str
    category: str
    annotations: Any
    morality: Optional[Any] = None
    user_id: str


class SentAnnotationOut(SentAnnotationIn):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# analysis  (category_name + today are path params, not body fields)
# ---------------------------------------------------------------------------

class AnalysisIn(BaseModel):
    frequency: int = 0


class AnalysisOut(BaseModel):
    category_name: str
    today: str
    frequency: int

    model_config = ConfigDict(from_attributes=True)