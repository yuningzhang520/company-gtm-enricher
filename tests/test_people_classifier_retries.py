import json
from types import SimpleNamespace

import pytest
from openai import APITimeoutError

from company_gtm_enricher.people.classification import OpenAIRoleClassifier
from company_gtm_enricher.people.models import CompanyTarget, PeopleCriteria
from company_gtm_enricher.people.search import SearchHit


def test_classifier_retries_the_same_saved_evidence_and_counts_all_attempts():
    observation = {
        "source_id": "hit-1", "name": "Alex Example", "title": "CEO",
        "department": "", "seniority": "C-level", "role_type": "leadership",
        "is_founder": False, "is_c_level": True, "current_employment": "current",
        "employment_quote": "CEO at Example", "classification_notes": "",
    }
    success = SimpleNamespace(status="completed", output=[], output_text=json.dumps({"observations": [observation]}), usage=SimpleNamespace(input_tokens=100, output_tokens=50))
    attempts, sleeps = [], []

    def create(**kwargs):
        attempts.append(kwargs)
        if len(attempts) < 3:
            raise APITimeoutError(request=SimpleNamespace())
        return success

    classifier = OpenAIRoleClassifier(SimpleNamespace(responses=SimpleNamespace(create=create)), max_retries=2, sleep=sleeps.append)
    candidates = classifier.classify(CompanyTarget("Example", "example.org"), PeopleCriteria(), [SearchHit("hit-1", "https://www.linkedin.com/in/alex-example", "Alex Example - CEO at Example", "CEO at Example")])
    assert len(candidates) == 1 and candidates[0].title == "CEO"
    assert len(attempts) == 3 and attempts[0] == attempts[1] == attempts[2]
    assert sleeps == [1.0, 2.0]
    assert classifier.usage == {"llm_requests": 3, "input_tokens": 100, "output_tokens": 50}


def test_classifier_exhaustion_is_sanitized_and_does_not_restart_search():
    attempts = []
    def create(**kwargs):
        attempts.append(kwargs)
        raise APITimeoutError(request=SimpleNamespace(headers={"secret": "private-key"}))
    classifier = OpenAIRoleClassifier(SimpleNamespace(responses=SimpleNamespace(create=create)), max_retries=1, sleep=lambda seconds: None)
    with pytest.raises(RuntimeError, match="timed out") as error:
        classifier.classify(CompanyTarget("Example", "example.org"), PeopleCriteria(), [SearchHit("hit-1", "https://www.linkedin.com/in/alex-example", "Alex Example - CEO at Example", "CEO at Example")])
    assert "private-key" not in str(error.value)
    assert len(attempts) == classifier.usage["llm_requests"] == 2
