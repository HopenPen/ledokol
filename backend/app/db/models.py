"""Схема БД. Инварианты — в схеме (CHECK, UNIQUE, FK), а не только в сервисах.

Деньги — Numeric(16,2), время — timestamptz (UTC), публичные id — UUIDv7, состояния — enum-строки с CHECK.
Мягкого удаления нет: событие отменяется статусом, компания удаляется вместе с данными (CASCADE).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, Date, DateTime, Enum, Float, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.db.session import Base

Money = Numeric(16, 2)
_dir = Enum("in", "out", name="direction", native_enum=False, create_constraint=True, length=3)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("owner_id", "external_id", name="uq_company_owner_external"),
        CheckConstraint("min_balance >= 0", name="ck_company_min_balance"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    external_id: Mapped[str] = mapped_column(String(32))          # company_id из выписки (C001)
    name: Mapped[str] = mapped_column(Text)
    legal_form: Mapped[str] = mapped_column(Enum("ООО", "ИП", "unknown", name="legal_form", native_enum=False,
                                                 create_constraint=True, length=8), default="unknown")
    industry: Mapped[str | None] = mapped_column(Text)
    tax_regime: Mapped[str] = mapped_column(Enum("unknown", "usn", "osno", "eskhn", name="tax_regime", native_enum=False,
                                                 create_constraint=True, length=8), default="unknown")
    min_balance: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))  # неснижаемый остаток = порог разрыва
    data_version: Mapped[int] = mapped_column(default=0)  # растёт при каждой загрузке выписки → сброс кеша модели
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    operations: Mapped[list[Operation]] = relationship(back_populates="company", cascade="all, delete-orphan",
                                                       passive_deletes=True)


class StatementImport(Base):
    """Журнал загрузок. Повторная загрузка того же файла — no-op (идемпотентность по sha256)."""

    __tablename__ = "statement_imports"
    __table_args__ = (UniqueConstraint("company_id", "sha256", name="uq_import_company_sha"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    rows_total: Mapped[int]
    rows_new: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint("company_id", "source_operation_id", name="uq_operation_source"),  # дозагрузка без дублей
        CheckConstraint("amount > 0", name="ck_operation_amount_positive"),
        CheckConstraint("counterparty_inn IS NULL OR length(counterparty_inn) IN (10, 12)", name="ck_operation_inn"),
        Index("ix_operations_company_date", "company_id", "op_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    source_operation_id: Mapped[str] = mapped_column(String(64))
    op_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    direction: Mapped[str] = mapped_column(_dir)
    counterparty_inn: Mapped[str | None] = mapped_column(String(12))
    counterparty_name: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text, default="")  # ПДн возможны: не логируется, в LLM не уходит
    balance_eod: Mapped[Decimal] = mapped_column(Money)
    category: Mapped[str] = mapped_column(String(32), default="unknown")
    category_source: Mapped[str] = mapped_column(Enum("rule", "counterparty", "ml", "user", "none", name="category_source",
                                                      native_enum=False, create_constraint=True, length=12),
                                                 default="none")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    quality: Mapped[str] = mapped_column(Enum("ok", "duplicate", "after_gap", name="op_quality", native_enum=False,
                                              create_constraint=True, length=10), default="ok")

    company: Mapped[Company] = relationship(back_populates="operations")


class PlannedEvent(Base):
    """Ожидаемое событие из ручного ввода, 1С или сценария. Источник виден пользователю."""

    __tablename__ = "planned_events"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_event_idempotency"),
        UniqueConstraint("company_id", "source", "external_ref", name="uq_event_external"),
        CheckConstraint("amount > 0", name="ck_event_amount_positive"),
        Index("ix_events_company_date", "company_id", "event_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    event_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    direction: Mapped[str] = mapped_column(_dir)
    kind: Mapped[str] = mapped_column(Enum("manual", "invoice_out", "invoice_in", "tax", "contract", name="event_kind",
                                           native_enum=False, create_constraint=True, length=12))
    source: Mapped[str] = mapped_column(Enum("manual", "1c", "fns", name="event_source", native_enum=False,
                                             create_constraint=True, length=8))
    title: Mapped[str] = mapped_column(Text)
    counterparty_key: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(Enum("certain", "likely", "unsure", name="event_confidence",
                                                 native_enum=False, create_constraint=True, length=8),
                                            default="likely")
    status: Mapped[str] = mapped_column(Enum("expected", "received", "partial", "missed", "cancelled",
                                             name="event_status", native_enum=False, create_constraint=True, length=10),
                                        default="expected")
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    external_ref: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
