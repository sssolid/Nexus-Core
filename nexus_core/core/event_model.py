from __future__ import annotations

import dataclasses
import datetime
import uuid
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Represents an event in the Nexus Core event bus system.
    
    Events are the primary means of communication between different components
    in the Nexus Core system. Each event has a type, which is used for routing,
    and optional payload data, which contains the event's context and content.
    """
    
    event_type: str = Field(..., description="The type of the event, used for routing")
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique identifier for the event")
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now, description="When the event was created")
    source: str = Field(..., description="The source component that generated the event")
    payload: Dict[str, Any] = Field(default_factory=dict, description="The event data")
    correlation_id: Optional[str] = Field(None, description="ID for tracking related events")
    
    class Config:
        """Pydantic model configuration."""
        
        arbitrary_types_allowed = True
        json_encoders = {
            datetime.datetime: lambda dt: dt.isoformat(),
            uuid.UUID: lambda id: str(id),
        }
    
    @classmethod
    def create(
        cls,
        event_type: str,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> Event:
        """Create a new event with auto-generated ID and timestamp.
        
        Args:
            event_type: The type of the event, used for routing.
            source: The source component that generated the event.
            payload: Optional data associated with the event.
            correlation_id: Optional ID for tracking related events.
            
        Returns:
            Event: A new Event instance.
        """
        return cls(
            event_type=event_type,
            source=source,
            payload=payload or {},
            correlation_id=correlation_id,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the event to a dictionary.
        
        Returns:
            Dict[str, Any]: The event as a dictionary.
        """
        return self.dict()
    
    def __str__(self) -> str:
        """Get a string representation of the event.
        
        Returns:
            str: A string representation of the event.
        """
        return f"Event(type={self.event_type}, id={self.event_id}, source={self.source})"


@dataclasses.dataclass
class EventSubscription:
    """Represents a subscription to events on the event bus.
    
    This class maintains information about an event subscription, including
    the subscriber's callback function and any filters that determine which
    events the subscriber receives.
    """
    
    subscriber_id: str
    event_type: str
    callback: Any  # Callable[[Event], None] but avoid circular imports
    filter_criteria: Optional[Dict[str, Any]] = None
    
    def matches_event(self, event: Event) -> bool:
        """Check if an event matches this subscription's criteria.
        
        Args:
            event: The event to check against this subscription.
            
        Returns:
            bool: True if the event should be delivered to this subscription.
        """
        if event.event_type != self.event_type and self.event_type != "*":
            return False
            
        if not self.filter_criteria:
            return True
            
        # Check if payload matches filter criteria
        for key, value in self.filter_criteria.items():
            if key not in event.payload or event.payload[key] != value:
                return False
                
        return True
