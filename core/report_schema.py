import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def person_key(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name).casefold().split())


class ReportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=80)
    count: int | None = Field(ge=0, le=2_147_483_647, strict=True)
    uncertain: bool

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(unicodedata.normalize("NFC", value).split())


class ReportExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["report", "unknown"]
    rows: list[ReportRow] = Field(max_length=30)
    date_text: str | None = Field(max_length=100)
    date_uncertain: bool


class ReportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[ReportRow] = Field(min_length=1, max_length=30)
    report_date: date | None
    date_proposed: bool = False
    source: str = Field(max_length=200)

    def problem(self) -> str | None:
        if self.report_date is None:
            return "Ngày chưa rõ. Gửi /ngay DD/MM/YYYY để chọn ngày báo cáo."
        keys: set[str] = set()
        for index, row in enumerate(self.rows, 1):
            if not row.name or row.count is None:
                return f"Dòng {index} chưa rõ. Gửi /sua {index} Tên: số đơn để sửa."
            key = person_key(row.name)
            if key in keys:
                return (
                    f"Tên ở dòng {index} bị trùng. Dùng /sua {index} Tên đầy đủ: số đơn "
                    f"để phân biệt người, hoặc /xoadong {index}."
                )
            keys.add(key)
        return None
