"""Validate the design schema in memory. Does not create the application DB."""
from pathlib import Path
import argparse
import json
import sqlite3


def verify():
    db = sqlite3.connect(":memory:")
    db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
    checks = []

    def insert(table, **values):
        names = ",".join(values)
        db.execute(f"INSERT INTO {table} ({names}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))

    def reject(name, statement, params=()):
        try:
            db.execute(statement, params)
        except sqlite3.IntegrityError:
            checks.append(name)
        else:
            raise AssertionError(f"Constraint did not reject: {name}")

    for user in ("u1", "u2"):
        insert("users", id=user, username=user, password_hash="test-hash", display_name=user)
    insert("knowledge_points", id="kp1", code="queue.circular", title="Circular queue")
    insert("knowledge_bases", id="kb1", owner_id="u1", title="Private", visibility="private")
    reject("private knowledge base requires owner", "INSERT INTO knowledge_bases(id,title,visibility) VALUES('kb2','bad','private')")
    insert("documents", id="d1", kb_id="kb1", filename="notes.md", storage_key="u1/d1.md", media_type="text/markdown", byte_size=12, content_sha256="sha1")
    reject("duplicate live document", "INSERT INTO documents(id,kb_id,filename,storage_key,media_type,byte_size,content_sha256) VALUES('d2','kb1','x','x','text/plain',1,'sha1')")
    version = dict(document_id="d1", embedding_profile="test", embedding_dimensions=3, collection_name="test", parser_version="v1", chunking_config_json="{}")
    insert("document_versions", id="v1", version_no=1, status="ready", is_active=1, **version)
    insert("document_versions", id="v2", version_no=2, status="ready", is_active=0, **version)
    reject("only one active document version", "UPDATE document_versions SET is_active=1 WHERE id='v2'")
    reject("unfinished version cannot be active", "UPDATE document_versions SET status='embedding' WHERE id='v1'")
    insert("document_chunks", id="c1", document_version_id="v1", ordinal=0, text_content="Queue reserves one slot", location_json='{"heading":"Queue"}', vector_point_id="c1", token_count=5)
    insert("chunk_knowledge_points", chunk_id="c1", knowledge_point_id="kp1")
    reject("unknown knowledge point", "INSERT INTO chunk_knowledge_points VALUES('c1','missing')")
    insert("conversations", id="conv1", user_id="u1", title="Queues")
    insert("messages", id="m1", conversation_id="conv1", sequence_no=1, role="user", content="Why?", status="completed")
    insert("messages", id="m2", conversation_id="conv1", sequence_no=2, role="assistant", reply_to_message_id="m1", status="generating")
    reject("one live generation per conversation", "INSERT INTO messages(id,conversation_id,sequence_no,role,reply_to_message_id,status) VALUES('m3','conv1',3,'assistant','m1','queued')")
    insert("conversations", id="conv2", user_id="u2", title="Other")
    reject("reply must reference the same conversation", "INSERT INTO messages(id,conversation_id,sequence_no,role,reply_to_message_id,status) VALUES('cross-reply','conv2',1,'assistant','m1','queued')")
    db.execute("UPDATE messages SET status='completed' WHERE id='m2'")
    insert("citations", id="cit1", message_id="m2", citation_no=1, chunk_id="c1", source_title="notes", location_json="{}", excerpt="Queue")
    insert("questions", id="q1", owner_id="u1", visibility="private", source_kind="ai")
    question = dict(question_id="q1", primary_knowledge_point_id="kp1", question_type="single_choice", difficulty=1, stem="Full condition?", options_json='[{"id":"A","text":"a"},{"id":"B","text":"b"}]', answer_json='{"option_id":"B"}', explanation="Reserves one slot", validation_status="verified", validation_method="program")
    insert("question_versions", id="qv1", version_no=1, **question)
    insert("question_sources", question_version_id="qv1", chunk_id="c1")
    reject("invalid JSON payload", "UPDATE question_versions SET options_json='invalid' WHERE id='qv1'")
    reject("verified question needs validator", "UPDATE question_versions SET validation_method=NULL WHERE id='qv1'")
    insert("practice_sessions", id="ps1", user_id="u1", mode="chapter", selection_config_json="{}", client_request_id="ps-req1", request_sha256="hash")
    insert("practice_items", id="pi1", session_id="ps1", user_id="u1", question_version_id="qv1", ordinal=1)
    reject("practice item must share session owner", "INSERT INTO practice_items VALUES('pi-other','ps1','u2','qv1',2,0)")
    reject("attempt must share item owner", "INSERT INTO attempts(id,practice_item_id,user_id,answer_json,outcome,weight,is_first_attempt,client_request_id,request_sha256) VALUES('wrong-owner','pi1','u2','{}','incorrect',1,1,'bad','h')")
    insert("attempts", id="a1", practice_item_id="pi1", user_id="u1", answer_json='{"option_id":"A"}', outcome="incorrect", weight=1, is_first_attempt=1, client_request_id="a-req1", request_sha256="h1")
    reject("one attempt per presented item", "INSERT INTO attempts(id,practice_item_id,user_id,answer_json,outcome,weight,is_first_attempt,client_request_id,request_sha256) VALUES('a2','pi1','u1','{}','correct',1,1,'other','h')")
    insert("practice_items", id="pi2", session_id="ps1", user_id="u1", question_version_id="qv1", ordinal=2)
    reject("request id unique per user", "INSERT INTO attempts(id,practice_item_id,user_id,answer_json,outcome,weight,is_first_attempt,client_request_id,request_sha256) VALUES('a3','pi2','u1','{}','correct',0.25,0,'a-req1','h')")
    insert("attempts", id="a2", practice_item_id="pi2", user_id="u1", answer_json='{"option_id":"B"}', outcome="correct", weight=0.25, is_first_attempt=0, client_request_id="a-req2", request_sha256="h2")
    insert("wrong_questions", id="w1", user_id="u1", question_id="q1", last_attempt_id="a1", incorrect_count=1)
    insert("review_records", id="r1", wrong_question_id="w1", attempt_id="a2")
    stats = db.execute("SELECT valid_attempt_count,correct_count,evidence_weight,performance_estimate FROM learning_stats").fetchone()
    assert stats[:3] == (2, 1, 1.25) and abs(stats[3] - 1.25 / 3.25) < 1e-9, stats
    checks.append("weighted statistics derive from actual attempts")
    db.execute("UPDATE attempts SET outcome='voided' WHERE id='a2'")
    assert db.execute("SELECT valid_attempt_count FROM learning_stats").fetchone() == (1,)
    checks.append("voided attempt excluded from statistics")
    db.execute("UPDATE question_versions SET validation_status='revoked' WHERE id='qv1'")
    assert db.execute("SELECT COUNT(*) FROM learning_stats").fetchone() == (0,)
    checks.append("revoked question excluded from statistics")
    insert("jobs", id="j1", user_id="u1", kind="ingest", target_id="v1")
    reject("one active job per target", "INSERT INTO jobs(id,user_id,kind,target_id) VALUES('j2','u1','ingest','v1')")
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    checks.append("foreign keys and integrity checks pass")
    table_count = db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    result = {"sqlite_version": sqlite3.sqlite_version, "tables": table_count, "checks_passed": len(checks), "checks": checks, "scope": "in-memory schema validation only"}
    db.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional UTF-8 verification report")
    args = parser.parse_args()
    output = json.dumps(verify(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
