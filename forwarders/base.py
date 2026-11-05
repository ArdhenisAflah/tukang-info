from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ForwardMessage:
    source: str
    sender: str
    text: str
    timestamp: datetime | None = None


class MessageForwarder(ABC):
    """Base class for forwarding a message to another chat system."""

    @abstractmethod
    def send(self, message: ForwardMessage) -> None:
        """Forward one message to the destination."""

    def close(self) -> None:
        """Release resources. Subclasses override when needed."""
