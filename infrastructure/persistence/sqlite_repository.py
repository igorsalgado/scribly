import sqlite3
from pathlib import Path
from datetime import datetime
from uuid import UUID

from domain.meeting import BusinessRules, Meeting, Participant, Transcript, TranscriptSegment
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
    def __init__(self, db_path: Path = Path("soundcatch.db")) -> None:
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    def save(self, meeting: Meeting) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meetings (id, date, duration_seconds, audio_path) VALUES (?, ?, ?, ?)",
                (
                    str(meeting.id),
                    meeting.date.isoformat(),
                    meeting.duration_seconds,
                    meeting.audio_path,
                ),
            )

            conn.execute(
                "DELETE FROM participants WHERE meeting_id = ?", (str(meeting.id),)
            )
            for participant in meeting.participants:
                conn.execute(
                    "INSERT INTO participants (meeting_id, label) VALUES (?, ?)",
                    (str(meeting.id), participant.label),
                )

            conn.execute(
                "DELETE FROM transcript_segments WHERE meeting_id = ?",
                (str(meeting.id),),
            )
            if meeting.transcript:
                for seg in meeting.transcript.segments:
                    conn.execute(
                        "INSERT INTO transcript_segments (meeting_id, start_time, end_time, text, speaker) VALUES (?, ?, ?, ?, ?)",
                        (str(meeting.id), seg.start, seg.end, seg.text, seg.speaker),
                    )

            conn.execute(
                "DELETE FROM business_rules WHERE meeting_id = ?", (str(meeting.id),)
            )
            if meeting.business_rules:
                conn.execute(
                    "INSERT INTO business_rules (meeting_id, raw_markdown) VALUES (?, ?)",
                    (str(meeting.id), meeting.business_rules.raw_markdown),
                )

    def find_by_id(self, meeting_id: UUID) -> "Meeting | None":
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM meetings WHERE id = ?", (str(meeting_id),)
            ).fetchone()
            if not row:
                return None
            return self._hydrate(conn, row)

    def find_all(self) -> list[Meeting]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM meetings ORDER BY date DESC").fetchall()
            return [self._hydrate(conn, row) for row in rows]

    def _hydrate(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Meeting:
        meeting_id = row["id"]

        participant_rows = conn.execute(
            "SELECT label FROM participants WHERE meeting_id = ?", (meeting_id,)
        ).fetchall()
        participants = [Participant(label=r["label"]) for r in participant_rows]

        segment_rows = conn.execute(
            "SELECT start_time, end_time, text, speaker FROM transcript_segments WHERE meeting_id = ? ORDER BY start_time",
            (meeting_id,),
        ).fetchall()
        segments = [
            TranscriptSegment(
                start=r["start_time"],
                end=r["end_time"],
                text=r["text"],
                speaker=r["speaker"],
            )
            for r in segment_rows
        ]
        transcript = Transcript(segments=segments) if segments else None

        br_row = conn.execute(
            "SELECT raw_markdown FROM business_rules WHERE meeting_id = ?",
            (meeting_id,),
        ).fetchone()
        business_rules = (
            BusinessRules(raw_markdown=br_row["raw_markdown"]) if br_row else None
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
