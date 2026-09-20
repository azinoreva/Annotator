import json
import re
from typing import Dict

from pydantic import BaseModel, Field

from models.aggregates import MAIN_CLASSIFICATIONS
from .model import ask_model


class AnnotationResult(BaseModel):
    classification: str
    correlations: Dict[str, float]

    class Config:
        extra = "forbid"


class FeedAnnotationEngine:

    def classify(self, post: str) -> str:
        prompt = self._classification_prompt(post)

        raw = ask_model(prompt)

        return self._extract_classification(raw)

    def correlate(
        self,
        post: str,
        classification: str,
    ) -> Dict[str, float]:

        subcategories = MAIN_CLASSIFICATIONS[classification]

        prompt = self._correlation_prompt(
            post,
            classification,
            subcategories,
        )

        raw = ask_model(prompt)

        return self._extract_correlations(
            raw,
            subcategories,
        )

    def annotate(self, post: str) -> AnnotationResult:

        classification = self.classify(post)

        correlations = self.correlate(
            post,
            classification,
        )

        return AnnotationResult(
            classification=classification,
            correlations=correlations,
        )

    # ---------------------------------------------------------
    # PROMPTS
    # ---------------------------------------------------------

    def _classification_prompt(self, post: str) -> str:

        categories = ", ".join(MAIN_CLASSIFICATIONS.keys())

        return f"""
Classify the following post into exactly ONE category.

Allowed categories:
{categories}

POST:
{post}

Your answer must contain one of the allowed category names.
Do not create another category.
"""

    def _correlation_prompt(
        self,
        post: str,
        classification: str,
        subcategories: list[str],
    ) -> str:

        categories = ", ".join(subcategories)

        return f"""
Analyze the following post.

Main classification:
{classification}

Possible subcategories:
{categories}

For every subcategory, determine how strongly the post relates to it.

Return a JSON object where:

- every allowed subcategory appears exactly once
- value is a number from 0.0 to 1.0
- 0.0 means no meaningful relationship
- 1.0 means extremely strong relationship
- values do NOT need to add up to 1.0
- do not create additional keys

POST:
{post}
"""

    # ---------------------------------------------------------
    # EXTRACTION
    # ---------------------------------------------------------

    def _extract_classification(self, raw: str) -> str:

        text = raw.strip().lower()

        # Exact answer first.
        if text in MAIN_CLASSIFICATIONS:
            return text

        # Look for category names inside the response.
        found = []

        for category in MAIN_CLASSIFICATIONS:

            pattern = rf"\b{re.escape(category.lower())}\b"

            if re.search(pattern, text):
                found.append(category)

        # Exactly one category mentioned.
        if len(found) == 1:
            return found[0]

        # Nothing useful or ambiguous.
        raise ValueError(
            f"Could not extract a unique classification "
            f"from model response: {raw!r}"
        )

    def _extract_correlations(
        self,
        raw: str,
        expected_keys: list[str],
    ) -> Dict[str, float]:

        data = self._extract_json_object(raw)

        if not isinstance(data, dict):
            raise ValueError(
                "Model correlation response is not a JSON object."
            )

        expected = set(expected_keys)
        received = set(data.keys())

        missing = expected - received
        extra = received - expected

        if missing:
            raise ValueError(
                f"Missing correlation keys: {sorted(missing)}"
            )

        if extra:
            raise ValueError(
                f"Unexpected correlation keys: {sorted(extra)}"
            )

        result = {}

        for key in expected_keys:

            value = data[key]

            # bool is technically an int in Python.
            # Explicitly reject it.
            if isinstance(value, bool):
                raise ValueError(
                    f"Correlation for {key!r} must be a number."
                )

            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"Correlation for {key!r} must be numeric."
                )

            value = float(value)

            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"Correlation for {key!r} must be "
                    f"between 0.0 and 1.0."
                )

            result[key] = value

        return result

    @staticmethod
    def _extract_json_object(raw: str) -> dict:

        text = raw.strip()

        # First try the entire response.
        try:
            value = json.loads(text)

            if isinstance(value, dict):
                return value

        except json.JSONDecodeError:
            pass

        # Look for a JSON object embedded in prose.
        decoder = json.JSONDecoder()

        for index, char in enumerate(text):

            if char != "{":
                continue

            try:
                value, _ = decoder.raw_decode(
                    text[index:]
                )

                if isinstance(value, dict):
                    return value

            except json.JSONDecodeError:
                continue

        raise ValueError(
            f"Could not find a JSON object in model response: "
            f"{raw!r}"
        )