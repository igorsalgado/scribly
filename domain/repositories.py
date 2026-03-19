from abc import ABC, abstractmethod
from uuid import UUID

from domain.meeting import Meeting


class MeetingRepository(ABC):
    @abstractmethod
    def save(self, meeting: Meeting) -> None: ...

    @abstractmethod
    def find_by_id(self, meeting_id: UUID) -> "Meeting | None": ...

    @abstractmethod
    def find_all(self) -> list[Meeting]: ...
