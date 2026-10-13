import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from app.models.schemas import FieldNode, field_id, normalize_field


class FieldCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS analysis_artifacts (
                    kind TEXT NOT NULL, artifact_key TEXT NOT NULL, payload TEXT NOT NULL,
                    expires_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY (kind, artifact_key)
                );
                CREATE TABLE IF NOT EXISTS fields (
                    cache_key TEXT PRIMARY KEY, field_id TEXT NOT NULL, name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL, payload TEXT NOT NULL,
                    expires_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS papers (
                    paper_key TEXT PRIMARY KEY, paper_id TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS field_relations (
                    cache_key TEXT NOT NULL REFERENCES fields(cache_key) ON DELETE CASCADE,
                    target_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
                    reason TEXT NOT NULL, confidence REAL NOT NULL, evidence TEXT NOT NULL,
                    PRIMARY KEY (cache_key, target_id, kind)
                );
                CREATE TABLE IF NOT EXISTS field_core_papers (
                    cache_key TEXT NOT NULL REFERENCES fields(cache_key) ON DELETE CASCADE,
                    paper_key TEXT NOT NULL REFERENCES papers(paper_key),
                    position INTEGER NOT NULL, score REAL NOT NULL, reason TEXT NOT NULL,
                    PRIMARY KEY (cache_key, paper_key)
                );
            ''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, key: str) -> FieldNode | None:
        with self.connect() as db:
            row = db.execute('SELECT payload FROM fields WHERE cache_key=? AND expires_at>?',
                             (key, time.time())).fetchone()
        if not row:
            return None
        return FieldNode.model_validate_json(row[0]).model_copy(update={'cache_hit': True})

    def save(self, key: str, node: FieldNode, ttl_seconds: float):
        # All related tables change in a single transaction; failed refreshes never replace a good result.
        with self.connect() as db:
            db.execute('INSERT INTO fields VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET '
                       'name=excluded.name, payload=excluded.payload, expires_at=excluded.expires_at, updated_at=excluded.updated_at',
                       (key, node.id, node.name, normalize_field(node.name), node.model_dump_json(),
                        time.time() + ttl_seconds, time.time()))
            db.execute('DELETE FROM field_relations WHERE cache_key=?', (key,))
            db.execute('DELETE FROM field_core_papers WHERE cache_key=?', (key,))
            for kind, relations in [('prerequisite', node.prerequisites), ('subfield', node.subfields)]:
                for r in relations:
                    db.execute('INSERT INTO field_relations VALUES (?, ?, ?, ?, ?, ?, ?)',
                               (key, field_id(r.name), kind, r.name, r.reason, r.confidence,
                                json.dumps(r.evidence_paper_ids)))
            for position, core in enumerate(node.core_papers):
                paper = core.paper
                paper_key = paper.source + ':' + paper.id
                db.execute('INSERT INTO papers VALUES (?, ?, ?, ?) ON CONFLICT(paper_key) DO UPDATE SET payload=excluded.payload',
                           (paper_key, paper.id, paper.source, paper.model_dump_json()))
                db.execute('INSERT INTO field_core_papers VALUES (?, ?, ?, ?, ?)',
                           (key, paper_key, position, core.score, core.reason))

    def count(self) -> int:
        with self.connect() as db:
            return db.execute('SELECT COUNT(DISTINCT field_id) FROM fields WHERE expires_at>?', (time.time(),)).fetchone()[0]

    def get_artifact(self, kind: str, key: str):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM analysis_artifacts WHERE kind=? AND artifact_key=? AND expires_at>?',
                             (kind, key, time.time())).fetchone()
        return json.loads(row[0]) if row else None

    def save_artifact(self, kind: str, key: str, value, ttl_seconds: float):
        with self.connect() as db:
            db.execute('INSERT INTO analysis_artifacts VALUES (?, ?, ?, ?, ?) ON CONFLICT(kind, artifact_key) '
                       'DO UPDATE SET payload=excluded.payload, expires_at=excluded.expires_at, updated_at=excluded.updated_at',
                       (kind, key, json.dumps(value, ensure_ascii=False), time.time() + ttl_seconds, time.time()))
