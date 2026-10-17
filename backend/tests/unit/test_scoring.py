from jobpilot.domain.scoring import DEFAULT_WEIGHTS, ProfileView, extract_skills, score_job


def view(skills=(), elig=None, langs=None) -> ProfileView:
    return ProfileView(version_id="v", skills={s: f"f-{s}" for s in skills}, eligibility=elig or {},
                       languages=langs or {})


ANDROID_JOB = {"title": "Android Developer", "description_text": "Kotlin, Java and Android with Gradle. English.",
               "country": "DE", "work_mode": "onsite"}


def test_weights_sum_to_100():
    assert sum(DEFAULT_WEIGHTS.values()) == 100


def test_breakdown_sums_to_score_and_respects_caps():
    r = score_job(ANDROID_JOB, view(["kotlin", "java", "android", "gradle"]))
    assert sum(r.breakdown.values()) == r.score
    for k, v in r.breakdown.items():
        assert 0 <= v <= DEFAULT_WEIGHTS[k]


def test_unverified_profile_scores_zero_on_skills():
    r = score_job(ANDROID_JOB, view([]))
    assert r.breakdown["technical"] == 0
    assert r.matched_skills == []
    assert set(r.missing_skills) == {"kotlin", "java", "android", "gradle"}


def test_every_matched_skill_has_evidence_linked_to_a_fact():
    r = score_job(ANDROID_JOB, view(["kotlin", "android"]))
    ev = [e for e in r.evidence if e["criterion"] == "technical"]
    assert {e["fact_id"] for e in ev} == {"f-kotlin", "f-android"}


def test_student_job_without_verified_enrolment_is_never_auto_recommended():
    job = {"title": "Werkstudent Softwareentwicklung", "description_text": "Java Kotlin Android", "country": "DE"}
    r = score_job(job, view(["java", "kotlin", "android"]))
    assert r.track == "D"
    assert any("enrolment" in u for u in r.eligibility["uncertain"])
    assert r.recommendation != "apply"


def test_verified_low_german_fails_mandatory_german():
    job = {"title": "Junior Java Developer", "description_text": "Java. Deutsch C1 erforderlich.", "country": "DE"}
    r = score_job(job, view(["java"], langs={"german": ("A2", "f-de")}))
    assert r.recommendation == "reject"
    assert r.eligibility["failed"]


def test_unverified_german_is_uncertain_not_rejected():
    job = {"title": "Junior Java Developer", "description_text": "Java. Deutsch C1 erforderlich.", "country": "DE"}
    r = score_job(job, view(["java"]))
    assert r.recommendation != "reject"
    assert any("German" in u for u in r.eligibility["uncertain"])


def test_high_score_with_work_authorization_doubt_is_review_not_apply():
    job = {"title": "Junior Android Developer", "country": "DE",
           "description_text": "Kotlin Java Android. EU citizens or unrestricted work permit only."}
    r = score_job(job, view(["kotlin", "java", "android"]))
    assert r.score >= 75
    assert r.recommendation == "review"


def test_skill_extraction_prefers_specific_spring_term():
    assert extract_skills("We use Spring Boot and C++") == ["c++", "spring boot"]


def test_german_level_is_taken_from_the_listing():
    from jobpilot.domain.scoring import detect_languages

    assert detect_languages("Gute Deutschkenntnisse (B2) und English")[0]["level"] == "B2"
    assert detect_languages("Deutsch fließend")[0]["level"] == "fluent"


def test_verified_b2_meets_b2_but_not_c1():
    b2 = view(["java"], langs={"german": ("B2", "f-de")})
    ok = score_job({"title": "Junior Java Developer", "description_text": "Java. Deutsch B2.", "country": "DE"}, b2)
    no = score_job({"title": "Junior Java Developer", "description_text": "Java. Deutsch C1.", "country": "DE"}, b2)
    assert not ok.eligibility["failed"] and no.recommendation == "reject"


def test_senior_roles_are_low_priority_even_with_skill_match():
    r = score_job({"title": "Senior Android Architect", "description_text": "8+ years Kotlin Android",
                   "country": "DE"}, view(["kotlin", "android"]))
    assert r.recommendation == "low_priority"
