from dataclasses import dataclass, field


@dataclass
class RetrievedContext:
    text: str
    source_id: str
    location: str = ""
    image_path: str = ""


@dataclass
class RAGResponse:
    answer: str
    contexts: list[RetrievedContext] = field(default_factory=list)
