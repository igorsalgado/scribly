from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from domain.meeting import (
    BusinessRules,
    Meeting,
    Participant,
    Transcript,
    TranscriptSegment,
)
from domain.repositories import MeetingRepository

_DDL = """
CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    duration_seconds REAL,
    audio_path TEXT
);
CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL,
    label TEXT NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);
CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL,
    start_time REAL,
    end_time REAL,
    text TEXT,
    speaker TEXT,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);
CREATE TABLE IF NOT EXISTS business_rules (
    meeting_id TEXT PRIMARY KEY,
    raw_markdown TEXT,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);
"""


class SQLiteMeetingRepository(MeetingRepository):
    def __init__(self, db_path: Path = Path("data/scribly.db")) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(_DDL)

    def save(self, meeting: Meeting) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO meetings (id, date, duration_seconds, audio_path)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(meeting.id),
                    meeting.date.isoformat(),
                    meeting.duration_seconds,
                    meeting.audio_path,
                ),
            )

            connection.execute(
                "DELETE FROM participants WHERE meeting_id = ?",
                (str(meeting.id),),
            )
            for participant in meeting.participants:
                connection.execute(
                    "INSERT INTO participants (meeting_id, label) VALUES (?, ?)",
                    (str(meeting.id), participant.label),
                )

            connection.execute(
                "DELETE FROM transcript_segments WHERE meeting_id = ?",
                (str(meeting.id),),
            )
            if meeting.transcript:
                for segment in meeting.transcript.segments:
                    connection.execute(
                        """
                        INSERT INTO transcript_segments (
                            meeting_id,
                            start_time,
                            end_time,
                            text,
                            speaker
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            str(meeting.id),
                            segment.start,
                            segment.end,
                            segment.text,
                            segment.speaker,
                        ),
                    )

            connection.execute(
                "DELETE FROM business_rules WHERE meeting_id = ?",
                (str(meeting.id),),
            )
            if meeting.business_rules:
                connection.execute(
                    """
                    INSERT INTO business_rules (meeting_id, raw_markdown)
                    VALUES (?, ?)
                    """,
                    (str(meeting.id), meeting.business_rules.raw_markdown),
                )

    def find_by_id(self, meeting_id: UUID) -> "Meeting | None":
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM meetings WHERE id = ?",
                (str(meeting_id),),
            ).fetchone()
            if not row:
                return None
            return self._hydrate(connection, row)

    def find_all(self) -> list[Meeting]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM meetings ORDER BY date DESC"
            ).fetchall()
            return [self._hydrate(connection, row) for row in rows]

    def _hydrate(self, connection: sqlite3.Connection, row: sqlite3.Row) -> Meeting:
        meeting_id = row["id"]

        participant_rows = connection.execute(
            "SELECT label FROM participants WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchall()
        participants = [Participant(label=item["label"]) for item in participant_rows]

        segment_rows = connection.execute(
            """
            SELECT start_time, end_time, text, speaker
            FROM transcript_segments
            WHERE meeting_id = ?
            ORDER BY start_time
            """,
            (meeting_id,),
        ).fetchall()
        segments = [
            TranscriptSegment(
                start=item["start_time"],
                end=item["end_time"],
                text=item["text"],
                speaker=item["speaker"],
            )
            for item in segment_rows
        ]
        transcript = Transcript(segments=segments) if segments else None

        business_rules_row = connection.execute(
            "SELECT raw_markdown FROM business_rules WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()
        business_rules = (
            BusinessRules(raw_markdown=business_rules_row["raw_markdown"])
            if business_rules_row
            else None
        )

        return Meeting(
            id=UUID(meeting_id),
            date=datetime.fromisoformat(row["date"]),
            audio_path=row["audio_path"],
            duration_seconds=row["duration_seconds"],
            participants=participants,
            transcript=transcript,
            business_rules=business_rules,
        )
