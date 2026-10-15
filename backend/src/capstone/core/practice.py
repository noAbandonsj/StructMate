from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Difficulty = Literal["basic", "intermediate", "advanced"]


class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_]+$")
    text: str = Field(min_length=1, max_length=1000)


class QuestionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["single_choice", "true_false"]
    stem: str = Field(min_length=1, max_length=4000)
    options: list[Option] = Field(min_length=2, max_length=6)
    answer: str = Field(min_length=1, max_length=16)
    explanation: str = Field(min_length=1, max_length=5000)
    hint: str = Field(default="先核对定义、输入条件和操作顺序，再逐项比较选项。", max_length=1000)

    @model_validator(mode="after")
    def consistent(self):
        keys = [item.key for item in self.options]
        texts = [item.text.strip() for item in self.options]
        if (
            len(set(keys)) != len(keys)
            or len(set(texts)) != len(texts)
            or self.answer not in keys
            or not all(texts)
            or not self.stem.strip()
            or not self.explanation.strip()
        ):
            raise ValueError("题目选项或参考答案格式无效")
        if self.type == "true_false" and set(keys) != {"true", "false"}:
            raise ValueError("判断题选项须为 true/false")
        return self


class AIQuestion(QuestionData):
    knowledge_point_id: UUID
    difficulty: Difficulty
    citation_numbers: list[int] = Field(default_factory=list, max_length=6)


class RequestKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class PracticeInput(RequestKey):
    mode: Literal["chapter", "adaptive"] = "chapter"
    question_source: Literal["bank", "ai"] = "bank"
    knowledge_point_ids: list[UUID] = Field(default_factory=list, max_length=31)
    count: int = Field(default=5, ge=1, le=20)
    difficulty: Difficulty = "basic"
    generation_requirements: str = Field(default="", max_length=1000)
    source_conversation_id: UUID | None = None

    @model_validator(mode="after")
    def bank_has_no_ai_requirements(self):
        if self.question_source == "bank" and self.generation_requirements:
            raise ValueError("题库模式不接受 AI 出题要求")
        return self


class ReviewInput(RequestKey):
    wrong_question_ids: list[UUID] = Field(min_length=1, max_length=20)


class SubmitInput(RequestKey):
    answer: str = Field(min_length=1, max_length=16)


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, value):
        if len(value.strip()) < 5:
            raise ValueError("请具体说明题目问题")
        return value.strip()
