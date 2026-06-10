
from pydantic import BaseModel, Field
from typing import List, Optional

class TemplateMetadata(BaseModel):
    id: str
    name: str
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    files: List[str] = Field(default_factory=list)

class Task(BaseModel):
    id: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None

class ValidationResult(BaseModel):
    score: float
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

