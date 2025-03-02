from __future__ import annotations
import dataclasses
import datetime
import uuid
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, Field
class Event(BaseModel):
    event_type: str = Field(..., description='The type of the event, used for routing')
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description='Unique identifier for the event')
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now, description='When the event was created')
    source: str = Field(..., description='The source component that generated the event')
    payload: Dict[str, Any] = Field(default_factory=dict, description='The event data')
    correlation_id: Optional[str] = Field(None, description='ID for tracking related events')
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {datetime.datetime: lambda dt: dt.isoformat(), uuid.UUID: lambda id: str(id)}
    @classmethod
    def create(cls, event_type: str, source: str, payload: Optional[Dict[str, Any]]=None, correlation_id: Optional[str]=None) -> Event:
        return cls(event_type=event_type, source=source, payload=payload or {}, correlation_id=correlation_id)
    def to_dict(self) -> Dict[str, Any]:
        return self.dict()
    def __str__(self) -> str:
        return f'Event(type={self.event_type}, id={self.event_id}, source={self.source})'
@dataclasses.dataclass
class EventSubscription:
    subscriber_id: str
    event_type: str
    callback: Any
    filter_criteria: Optional[Dict[str, Any]] = None
    def matches_event(self, event: Event) -> bool:
        if event.event_type != self.event_type and self.event_type != '*':
            return False
        if not self.filter_criteria:
            return True
        for key, value in self.filter_criteria.items():
            if key not in event.payload or event.payload[key] != value:
                return False
        return True