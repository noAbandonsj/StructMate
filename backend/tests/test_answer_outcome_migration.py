from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import Session

from capstone.db.models import Conversation, User


def test_upgrade_classifies_only_old_fallback_without_rewriting_history(
    migrated_database, migration_config
):
    command.downgrade(migration_config, "0007")
    user_id, conversation_id = uuid4(), uuid4()
    with Session(migrated_database) as session, session.begin():
        session.add(
            User(id=user_id, username="migration_user", display_name="同学", password_hash="hash")
        )
        session.flush()
        session.add(Conversation(id=conversation_id, user_id=user_id))
    fallback = "当前资料没有找到足够依据。请补充已就绪资料、切换资料范围或把问题描述得更具体。"
    timestamp = "2026-10-01 10:00:00.000000"
    messages = sa.table(
        "messages",
        *(
            sa.column(name)
            for name in (
                "id",
                "conversation_id",
                "sequence",
                "role",
                "status",
                "intent",
                "content",
                "citations",
                "created_at",
                "updated_at",
            )
        ),
    )
    with migrated_database.begin() as connection:
        connection.execute(
            messages.insert(),
            [
                {
                    "id": uuid4().hex,
                    "conversation_id": conversation_id.hex,
                    "sequence": index,
                    "role": role,
                    "status": status,
                    "intent": "explain",
                    "content": content,
                    "citations": citations,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                for index, (role, status, content, citations) in enumerate(
                    [
                        ("user", "completed", fallback, "[]"),
                        ("assistant", "completed", fallback, "[]"),
                        ("assistant", "completed", "栈后进先出。", "[]"),
                        ("assistant", "completed", fallback, '[{"number": 1}]'),
                        ("assistant", "cancelled", "", "[]"),
                    ],
                    1,
                )
            ],
        )
    command.upgrade(migration_config, "head")
    with migrated_database.connect() as connection:
        rows = connection.execute(
            sa.text("SELECT answer_outcome, updated_at FROM messages ORDER BY sequence")
        ).all()
        assert [row.answer_outcome for row in rows] == [
            None,
            "insufficient_materials",
            "answered",
            "answered",
            None,
        ]
        assert all(row.updated_at == timestamp for row in rows)
    command.check(migration_config)
