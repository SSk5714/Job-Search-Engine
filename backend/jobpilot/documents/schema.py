from pydantic import BaseModel, Field


class Claim(BaseModel):
    text: str = Field(description="One sentence or bullet, in English")
    fact_ids: list[str] = Field(description="Ids of the verified facts this text rests on; empty only for "
                                            "courtesy sentences that state nothing about the candidate")


class SkillGroup(BaseModel):
    name: str = Field(description="Group label, e.g. 'Android platform', 'Languages', 'Currently learning'")
    skill_fact_ids: list[str] = Field(description="Ids of verified skill facts, most relevant first")


class ExperienceBlock(BaseModel):
    entry: str = Field(description="The employment entry label, e.g. 'sasken'")
    bullets: list[Claim]


class ProjectBlock(BaseModel):
    entry: str = Field(description="The project entry label")
    bullets: list[Claim]


class CVContent(BaseModel):
    headline: Claim = Field(description="Short professional headline, e.g. 'Android Platform Engineer'")
    summary: list[Claim] = Field(description="2-3 sentences tailored to the job")
    skill_groups: list[SkillGroup]
    experience: list[ExperienceBlock]
    projects: list[ProjectBlock] = Field(description="Most relevant projects first, at most 4")
    education_entries: list[str] = Field(description="Education entry labels in display order")
    certification_fact_ids: list[str] = Field(default_factory=list)


class Paragraph(BaseModel):
    sentences: list[Claim]


class LetterContent(BaseModel):
    subject: str = Field(description="e.g. 'Application for the position of Android Developer'")
    salutation: str = Field(description="e.g. 'Dear Hiring Team,'")
    paragraphs: list[Paragraph] = Field(description="3-4 short paragraphs")
    sign_off: str = Field(description="e.g. 'Kind regards,'")
