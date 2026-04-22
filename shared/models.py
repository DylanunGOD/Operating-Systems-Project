from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Task:
    id: str
    input_path: str
    output_path: Optional[str] = None
    status: str = "pending"


@dataclass
class Job:
    id: str
    tasks: List[Task] = field(default_factory=list)
    status: str = "created"
