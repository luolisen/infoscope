from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class ScopeId(StrEnum):
    AI = "ai"
    OPEN_SOURCE = "open_source"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    INVESTMENT = "investment"


class InvestmentMarketId(StrEnum):
    CHINA_MARKET = "china_market"
    US_STOCK = "us_stock"
    CRYPTO_MARKET = "crypto_market"


class FocusId(StrEnum):
    TECHNICAL_DETAILS = "technical_details"
    RESEARCH_PROGRESS = "research_progress"
    MAJOR_CHANGES = "major_changes"
    BREAKING_EVENTS = "breaking_events"
    NICHE_TRENDS = "niche_trends"
    INDUSTRY_CHANGES = "industry_changes"
    CONTROVERSY_CHANGES = "controversy_changes"
    DEEP_CONTEXT = "deep_context"


class ScopeOption(BaseModel):
    id: ScopeId
    label: str


class InvestmentMarketOption(BaseModel):
    id: InvestmentMarketId
    label: str


class FocusOption(BaseModel):
    id: FocusId
    label: str


class OnboardingSelection(BaseModel):
    scope_ids: list[ScopeId] = Field(min_length=1)
    investment_market_ids: list[InvestmentMarketId]
    focus_ids: list[FocusId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if len(set(self.scope_ids)) != len(self.scope_ids):
            raise ValueError("scope_ids must not contain duplicates")
        if len(set(self.investment_market_ids)) != len(self.investment_market_ids):
            raise ValueError("investment_market_ids must not contain duplicates")
        if len(set(self.focus_ids)) != len(self.focus_ids):
            raise ValueError("focus_ids must not contain duplicates")

        includes_investment = ScopeId.INVESTMENT in self.scope_ids
        if includes_investment and not self.investment_market_ids:
            raise ValueError("investment_market_ids is required for investment scope")
        if not includes_investment and self.investment_market_ids:
            raise ValueError("investment_market_ids must be empty without investment scope")
        return self


class OnboardingAnswers(BaseModel):
    scope_ids: list[ScopeId]
    investment_market_ids: list[InvestmentMarketId]
    focus_ids: list[FocusId]


class OnboardingResponse(BaseModel):
    completed: bool
    scope_options: list[ScopeOption]
    investment_market_options: list[InvestmentMarketOption]
    focus_options: list[FocusOption]
    answers: OnboardingAnswers


SCOPE_OPTIONS = [
    ScopeOption(id=ScopeId.AI, label="AI"),
    ScopeOption(id=ScopeId.OPEN_SOURCE, label="开源社区"),
    ScopeOption(id=ScopeId.TECHNOLOGY, label="技术"),
    ScopeOption(id=ScopeId.SCIENCE, label="科学"),
    ScopeOption(id=ScopeId.INVESTMENT, label="投资"),
]

INVESTMENT_MARKET_OPTIONS = [
    InvestmentMarketOption(id=InvestmentMarketId.CHINA_MARKET, label="中国市场"),
    InvestmentMarketOption(id=InvestmentMarketId.US_STOCK, label="美股"),
    InvestmentMarketOption(id=InvestmentMarketId.CRYPTO_MARKET, label="加密市场"),
]

FOCUS_OPTIONS = [
    FocusOption(id=FocusId.TECHNICAL_DETAILS, label="技术细节"),
    FocusOption(id=FocusId.RESEARCH_PROGRESS, label="研究进展"),
    FocusOption(id=FocusId.MAJOR_CHANGES, label="重要变化"),
    FocusOption(id=FocusId.BREAKING_EVENTS, label="突发事件"),
    FocusOption(id=FocusId.NICHE_TRENDS, label="小众趋势"),
    FocusOption(id=FocusId.INDUSTRY_CHANGES, label="行业变化"),
    FocusOption(id=FocusId.CONTROVERSY_CHANGES, label="争议变化"),
    FocusOption(id=FocusId.DEEP_CONTEXT, label="深度背景"),
]
