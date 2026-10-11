-- Design baseline v0.1: apply to an EMPTY SQLite database only.
-- HISTORICAL DRAFT: superseded by the v0.2 database design (16 suggested entities).
-- Kept for comparison; do not use this 26-table draft as the current implementation plan.
-- IDs are UUID strings assigned by the application; timestamps are UTC ISO 8601.
-- Re-enable foreign_keys and busy_timeout on EVERY application connection.
-- Runtime WAL configuration and Alembic migrations belong to implementation.
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
BEGIN;

CREATE TABLE users (
    id TEXT PRIMARY KEY NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    learning_revision INTEGER NOT NULL DEFAULT 0 CHECK (learning_revision >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE auth_sessions (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_auth_sessions_user ON auth_sessions(user_id, expires_at);

CREATE TABLE knowledge_points (
    id TEXT PRIMARY KEY NOT NULL,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    parent_id TEXT REFERENCES knowledge_points(id),
    sort_order INTEGER NOT NULL DEFAULT 0,
    CHECK (parent_id IS NULL OR parent_id <> id)
);
CREATE INDEX ix_knowledge_points_parent ON knowledge_points(parent_id);

CREATE TABLE knowledge_bases (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT REFERENCES users(id),
    title TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('private','course')),
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((visibility='private' AND owner_id IS NOT NULL)
        OR (visibility='course' AND owner_id IS NULL))
);
CREATE INDEX ix_knowledge_bases_owner ON knowledge_bases(owner_id, deleted_at);

CREATE TABLE documents (
    id TEXT PRIMARY KEY NOT NULL,
    kb_id TEXT NOT NULL REFERENCES knowledge_bases(id),
    filename TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    content_sha256 TEXT NOT NULL,
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX uq_live_document_hash ON documents(kb_id, content_sha256)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_documents_kb ON documents(kb_id, deleted_at);

CREATE TABLE document_versions (
    id TEXT PRIMARY KEY NOT NULL,
    document_id TEXT NOT NULL REFERENCES documents(id),
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','parsing','chunking','embedding','ready','failed','cancelled')),
    is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1)),
    embedding_profile TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    collection_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    chunking_config_json TEXT NOT NULL CHECK (json_valid(chunking_config_json)),
    error_code TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(document_id, version_no),
    CHECK (is_active = 0 OR status = 'ready')
);
CREATE UNIQUE INDEX uq_active_document_version ON document_versions(document_id)
    WHERE is_active = 1;

CREATE TABLE document_chunks (
    id TEXT PRIMARY KEY NOT NULL,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    text_content TEXT NOT NULL,
    location_json TEXT NOT NULL CHECK (json_valid(location_json)),
    vector_point_id TEXT NOT NULL UNIQUE,
    token_count INTEGER NOT NULL CHECK (token_count >= 0),
    UNIQUE(document_version_id, ordinal)
);

CREATE TABLE chunk_knowledge_points (
    chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id),
    PRIMARY KEY(chunk_id, knowledge_point_id)
);
CREATE INDEX ix_chunk_kp_reverse ON chunk_knowledge_points(knowledge_point_id, chunk_id);

CREATE TABLE conversations (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    teaching_mode TEXT NOT NULL DEFAULT 'explain' CHECK (teaching_mode IN ('explain','guide')),
    archived_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(id, user_id)
);
CREATE INDEX ix_conversations_user ON conversations(user_id, created_at);

CREATE TABLE conversation_knowledge_bases (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    kb_id TEXT NOT NULL REFERENCES knowledge_bases(id),
    PRIMARY KEY(conversation_id, kb_id)
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    reply_to_message_id TEXT,
    content TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('queued','generating','completed','failed','cancelled')),
    generation_meta_json TEXT CHECK (generation_meta_json IS NULL OR json_valid(generation_meta_json)),
    client_request_id TEXT,
    request_sha256 TEXT,
    error_code TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(conversation_id, sequence_no),
    UNIQUE(conversation_id, client_request_id),
    UNIQUE(id, conversation_id),
    FOREIGN KEY(reply_to_message_id, conversation_id) REFERENCES messages(id, conversation_id),
    CHECK ((role='user' AND reply_to_message_id IS NULL)
        OR (role='assistant' AND reply_to_message_id IS NOT NULL))
);
CREATE UNIQUE INDEX uq_active_generation_per_conversation ON messages(conversation_id)
    WHERE role='assistant' AND status IN ('queued','generating');

CREATE TABLE citations (
    id TEXT PRIMARY KEY NOT NULL,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    citation_no INTEGER NOT NULL CHECK (citation_no > 0),
    chunk_id TEXT REFERENCES document_chunks(id) ON DELETE SET NULL,
    source_title TEXT NOT NULL,
    location_json TEXT NOT NULL CHECK (json_valid(location_json)),
    excerpt TEXT NOT NULL,
    UNIQUE(message_id, citation_no)
);

CREATE TABLE questions (
    id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT REFERENCES users(id),
    visibility TEXT NOT NULL CHECK (visibility IN ('private','course')),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('curated','ai')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((visibility='private' AND owner_id IS NOT NULL)
        OR (visibility='course' AND owner_id IS NULL))
);
CREATE INDEX ix_questions_owner ON questions(owner_id, visibility);

CREATE TABLE question_versions (
    id TEXT PRIMARY KEY NOT NULL,
    question_id TEXT NOT NULL REFERENCES questions(id),
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    primary_knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id),
    question_type TEXT NOT NULL CHECK (question_type IN ('single_choice','true_false')),
    difficulty INTEGER NOT NULL CHECK (difficulty BETWEEN 1 AND 3),
    stem TEXT NOT NULL,
    options_json TEXT NOT NULL CHECK (json_valid(options_json)),
    answer_json TEXT NOT NULL CHECK (json_valid(answer_json)),
    explanation TEXT NOT NULL,
    hint TEXT NOT NULL DEFAULT '',
    validation_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (validation_status IN ('draft','verified','revoked')),
    validation_method TEXT CHECK (validation_method IN ('manual','program')),
    generation_meta_json TEXT CHECK (generation_meta_json IS NULL OR json_valid(generation_meta_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(question_id, version_no),
    CHECK (validation_status <> 'verified' OR validation_method IS NOT NULL)
);
CREATE INDEX ix_question_versions_selection
    ON question_versions(primary_knowledge_point_id, difficulty, validation_status);

CREATE TABLE question_sources (
    question_version_id TEXT NOT NULL REFERENCES question_versions(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES document_chunks(id),
    PRIMARY KEY(question_version_id, chunk_id)
);

CREATE TABLE practice_sessions (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    mode TEXT NOT NULL CHECK (mode IN ('chapter','adaptive','review')),
    status TEXT NOT NULL DEFAULT 'preparing'
        CHECK (status IN ('preparing','ready','in_progress','completed','failed','cancelled')),
    selection_config_json TEXT NOT NULL CHECK (json_valid(selection_config_json)),
    client_request_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(id, user_id),
    UNIQUE(user_id, client_request_id)
);
CREATE INDEX ix_practice_sessions_user ON practice_sessions(user_id, created_at);

CREATE TABLE practice_items (
    id TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    question_version_id TEXT NOT NULL REFERENCES question_versions(id),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    hint_used INTEGER NOT NULL DEFAULT 0 CHECK (hint_used IN (0,1)),
    FOREIGN KEY(session_id, user_id) REFERENCES practice_sessions(id, user_id),
    UNIQUE(session_id, ordinal),
    UNIQUE(id, user_id)
);
CREATE INDEX ix_practice_items_version ON practice_items(question_version_id);

CREATE TABLE attempts (
    id TEXT PRIMARY KEY NOT NULL,
    practice_item_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    answer_json TEXT NOT NULL CHECK (json_valid(answer_json)),
    outcome TEXT NOT NULL CHECK (outcome IN ('correct','incorrect','voided')),
    weight REAL NOT NULL CHECK (weight > 0 AND weight <= 1),
    is_first_attempt INTEGER NOT NULL CHECK (is_first_attempt IN (0,1)),
    client_request_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    submitted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(practice_item_id, user_id) REFERENCES practice_items(id, user_id),
    UNIQUE(user_id, client_request_id)
);
CREATE INDEX ix_attempts_user_time ON attempts(user_id, submitted_at);

CREATE TABLE wrong_questions (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    question_id TEXT NOT NULL REFERENCES questions(id),
    last_attempt_id TEXT REFERENCES attempts(id),
    incorrect_count INTEGER NOT NULL DEFAULT 0 CHECK (incorrect_count >= 0),
    consecutive_correct INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_correct >= 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','reviewing','consolidated','voided')),
    next_review_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(user_id, question_id)
);
CREATE INDEX ix_wrong_questions_due ON wrong_questions(user_id, status, next_review_at);

CREATE TABLE review_records (
    id TEXT PRIMARY KEY NOT NULL,
    wrong_question_id TEXT NOT NULL REFERENCES wrong_questions(id),
    attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id),
    reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE question_feedback (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    practice_item_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(practice_item_id, user_id) REFERENCES practice_items(id, user_id),
    UNIQUE(user_id, practice_item_id)
);

CREATE TABLE conversation_summaries (
    id TEXT PRIMARY KEY NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    through_sequence_no INTEGER NOT NULL CHECK (through_sequence_no > 0),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','generating','completed','failed')),
    markdown_content TEXT NOT NULL DEFAULT '',
    generation_meta_json TEXT CHECK (generation_meta_json IS NULL OR json_valid(generation_meta_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE learning_reports (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    range_start_at TEXT NOT NULL,
    range_end_at TEXT NOT NULL,
    report_timezone TEXT NOT NULL,
    data_cutoff_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','generating','completed','failed')),
    stats_snapshot_json TEXT NOT NULL CHECK (json_valid(stats_snapshot_json)),
    markdown_content TEXT NOT NULL DEFAULT '',
    calculation_version TEXT NOT NULL,
    generation_meta_json TEXT CHECK (generation_meta_json IS NULL OR json_valid(generation_meta_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (range_start_at < range_end_at)
);
CREATE INDEX ix_reports_user ON learning_reports(user_id, created_at);

CREATE TABLE resources (
    id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    difficulty INTEGER NOT NULL CHECK (difficulty BETWEEN 1 AND 3),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','unavailable')),
    last_checked_at TEXT
);

CREATE TABLE resource_knowledge_points (
    resource_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    knowledge_point_id TEXT NOT NULL REFERENCES knowledge_points(id),
    PRIMARY KEY(resource_id, knowledge_point_id)
);
CREATE INDEX ix_resource_kp_reverse ON resource_knowledge_points(knowledge_point_id, resource_id);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('ingest','delete_document','chat','practice','summary','report')),
    target_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed','cancelled')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    client_request_id TEXT,
    request_sha256 TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(user_id, kind, client_request_id)
);
CREATE INDEX ix_jobs_status ON jobs(status, created_at);
CREATE UNIQUE INDEX uq_active_job_target ON jobs(kind, target_id)
    WHERE status IN ('queued','running');

-- Derived facts only: rolling time window and timezone grouping are applied by API queries.
-- Report snapshots use these facts plus the selected range; no second mutable score table.
CREATE VIEW learning_stats AS
SELECT a.user_id,
       qv.primary_knowledge_point_id AS knowledge_point_id,
       COUNT(*) AS valid_attempt_count,
       SUM(CASE WHEN a.outcome='correct' THEN 1 ELSE 0 END) AS correct_count,
       SUM(a.weight) AS evidence_weight,
       (1.0 + SUM(CASE WHEN a.outcome='correct' THEN a.weight ELSE 0 END))
           / (2.0 + SUM(a.weight)) AS performance_estimate
FROM attempts a
JOIN practice_items pi ON pi.id=a.practice_item_id
JOIN question_versions qv ON qv.id=pi.question_version_id
WHERE a.outcome IN ('correct','incorrect') AND qv.validation_status='verified'
GROUP BY a.user_id, qv.primary_knowledge_point_id;

COMMIT;
