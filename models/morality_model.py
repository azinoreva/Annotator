from typing import List, Literal
from pydantic import BaseModel, Field


class Subcategory(BaseModel):
    name: str
    intensity_percent: int = Field(ge=0, le=100)


class Flag(BaseModel):
    name: str
    intensity_percent: int = Field(ge=0, le=100)
    severity_percent: int = Field(ge=0, le=100)
    subcategories: List[Subcategory]


class ContentContext(BaseModel):
    stance: Literal[
        "endorsed",
        "quoted",
        "condemned",
        "educational",
        "fictional",
        "descriptive",
        "unclear"
    ]


class ContentSafetyAnnotation(BaseModel):
    schema_version: Literal["1.0"]
    flags: List[Flag]
    context: ContentContext