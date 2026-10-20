"""Maintainer import for verified external resource links; never fetches remote content."""

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from capstone.core.settings import Settings
from capstone.db.models import KnowledgePoint, Resource
from capstone.db.session import create_database_engine, write_transaction


class ResourceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    knowledge_point_code: str
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=2000)
    url: HttpUrl
    difficulty: Literal["basic", "intermediate", "advanced"]
    language: str = Field(min_length=1, max_length=40)
    author: str = Field(min_length=1)
    license: str = Field(min_length=1)
    checked_on: date
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def public_link(cls, value):
        if value.username or value.password:
            raise ValueError("资源地址不能包含身份凭据")
        return value


def import_resources(engine, packet):
    entries = [
        ResourceData.model_validate(item)
        for item in json.loads(Path(packet).read_text(encoding="utf-8"))
    ]
    if len({item.code for item in entries}) != len(entries):
        raise ValueError("资源编号重复")
    added = updated = skipped = 0
    with Session(engine) as session, write_transaction(session):
        points = {point.code: point.id for point in session.scalars(select(KnowledgePoint))}
        if any(item.knowledge_point_code not in points for item in entries):
            raise ValueError("资源知识点不存在，请先初始化目录")
        for item in entries:
            values = {
                "knowledge_point_id": points[item.knowledge_point_code],
                "title": item.title,
                "description": item.description,
                "url": str(item.url),
                "difficulty": item.difficulty,
                "language": item.language,
                "is_active": item.is_active,
                "source_info": {
                    "author": item.author,
                    "license": item.license,
                    "checked_on": item.checked_on.isoformat(),
                },
            }
            existing = session.scalar(select(Resource).where(Resource.code == item.code))
            if existing is None:
                session.add(Resource(code=item.code, **values))
                added += 1
            elif all(getattr(existing, key) == value for key, value in values.items()):
                skipped += 1
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
                updated += 1
    return added, updated, skipped


def main():
    parser = argparse.ArgumentParser(description="导入或更新维护的真实资源外链，不复制网页正文")
    parser.add_argument(
        "--file", type=Path, required=True, help="管理员维护的资源 JSON 文件（无内置外链）"
    )
    args = parser.parse_args()
    engine = create_database_engine(Settings().sqlite_path)
    try:
        added, updated, skipped = import_resources(engine, args.file)
        print(
            f"新增 {added}，更新 {updated}，未变 {skipped}。"
            "停用资源请将 is_active 设为 false 后导入。"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
