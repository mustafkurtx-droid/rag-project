from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Domain = Literal["finance", "risk", "economics", "econometrics", "regulation"]


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="", max_length=300)
    domain: Domain = "finance"
    document_type: str = Field(default="research", max_length=80)
    institution: str = Field(default="", max_length=150)
    publication_date: date | None = None
    language: str = Field(default="unknown", max_length=20)
    geography: str = Field(default="", max_length=80)
    risk_type: str = Field(default="", max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=30)
    source_url: str = Field(default="", max_length=2000)

    @field_validator("source_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("source_url must be an http(s) URL; it is provenance, not a download.")
        return value


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str | None = None
    domain: Domain | None = None
    institution: str | None = None
    geography: str | None = None
    risk_type: str | None = None
    as_of: date | None = None


class Page(BaseModel):
    number: int = Field(ge=1)
    markdown: str


class Chunk(BaseModel):
    id: str
    document_id: str
    page: int
    section: str
    kind: str
    text: str
    embedding_text: str
    fragmented: bool = False
