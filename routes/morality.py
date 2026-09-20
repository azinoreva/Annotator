from typing import List, Literal
from pydantic import BaseModel, Field, ValidationError
import json


# ============================================================
# PYDANTIC SCHEMA
# ============================================================

class Subcategory(BaseModel):
    name: str
    intensity_percent: int = Field(ge=0, le=100)


class Flag(BaseModel):
    name: str
    intensity_percent: int = Field(ge=0, le=100)
    severity_percent: int = Field(ge=0, le=100)
    subcategories: List[Subcategory]


class ContentContext(BaseModel):
    stance: Literal[
        "endorsed",
        "quoted",
        "condemned",
        "educational",
        "fictional",
        "descriptive",
        "unclear"
    ]


class ContentSafetyAnnotation(BaseModel):
    schema_version: Literal["1.0"]
    flags: List[Flag]
    context: ContentContext


# ============================================================
# CONTENT TAXONOMY
# ============================================================

CONTENT_FLAGS = {
    "profanity_vulgarity": [
        "swearing",
        "obscene_language",
        "crude_insult",
        "vulgar_gesture",
        "sexual_profanity",
    ],

    "sexual_content": [
        "suggestive",
        "sexual_reference",
        "explicit_sexual_description",
        "sexual_solicitation",
        "sexual_exploitation",
    ],

    "hate_discrimination": [
        "racial",
        "ethnic",
        "religious",
        "gender_based",
        "sexual_orientation",
        "disability",
        "xenophobic",
        "other_identity_based",
    ],

    "harassment_abuse": [
        "personal_attack",
        "bullying",
        "humiliation",
        "threat",
        "targeted_abuse",
        "stalking_or_intimidation",
    ],

    "violence_gore": [
        "violent_threat",
        "physical_violence",
        "graphic_injury",
        "blood_or_gore",
        "torture",
        "animal_violence",
    ],

    "bodily_gross_content": [
        "excrement",
        "vomit",
        "bodily_fluids",
        "bodily_functions",
        "decay_or_decomposition",
        "gross_imagery",
    ],

    "drug_substance_content": [
        "drug_use",
        "intoxication",
        "substance_abuse",
        "drug_promotion",
        "drug_instructions",
    ],

    "self_harm_suicide": [
        "self_harm_reference",
        "self_harm_ideation",
        "suicide_reference",
        "suicide_encouragement",
        "graphic_self_injury",
    ],

    "disturbing_traumatic_content": [
        "death",
        "disaster",
        "trauma",
        "disturbing_imagery",
        "distressing_event",
    ],

    "dangerous_harmful_activity": [
        "dangerous_challenge",
        "harmful_instructions",
        "reckless_endangerment",
        "hazardous_activity",
    ],
}


# ============================================================
# ENGINE
# ============================================================

class ContentSafetyEngine:

    SCHEMA_VERSION = "1.0"

    STANCES = [
        "endorsed",
        "quoted",
        "condemned",
        "educational",
        "fictional",
        "descriptive",
        "unclear",
    ]

    def __init__(self):
        self.flags = CONTENT_FLAGS

    # --------------------------------------------------------
    # TAXONOMY
    # --------------------------------------------------------

    def taxonomy_text(self) -> str:
        """
        Creates a readable representation of the allowed
        flags and subcategories for the AI.
        """

        lines = []

        for flag, subcategories in self.flags.items():

            lines.append(f"- {flag}")

            for subcategory in subcategories:
                lines.append(f"  - {subcategory}")

        return "\n".join(lines)

    # --------------------------------------------------------
    # OUTPUT EXAMPLE
    # --------------------------------------------------------

    def output_example(self) -> dict:
        """
        Creates the JSON structure expected from the AI.
        """

        return {
            "schema_version": self.SCHEMA_VERSION,

            "flags": [
                {
                    "name": "profanity_vulgarity",
                    "intensity_percent": 80,
                    "severity_percent": 60,
                    "subcategories": [
                        {
                            "name": "swearing",
                            "intensity_percent": 90
                        }
                    ]
                }
            ],

            "context": {
                "stance": "endorsed"
            }
        }

    # --------------------------------------------------------
    # SYSTEM MESSAGE
    # --------------------------------------------------------

    def system_message(self) -> str:

        return f"""
You are NULL's content safety annotation engine.

Your job is to analyze user-generated posts and identify
potentially vulgar, sexual, hateful, abusive, violent,
disgusting, disturbing, dangerous, or harmful content.

You are an annotation engine.

You are NOT a moderator.

Do not decide whether content should be deleted,
hidden, promoted, suppressed, or banned.

Your task is only to identify and describe the content.

------------------------------------------------------------
ALLOWED FLAGS
------------------------------------------------------------

You may ONLY use the following flags and subcategories:

{self.taxonomy_text()}

Do not invent new flags.

Do not invent new subcategories.

------------------------------------------------------------
FLAG SCORING
------------------------------------------------------------

Each detected flag must contain:

intensity_percent
severity_percent

Both values must be integers between 0 and 100.

INTENSITY:

0       = absent
1-20    = very mild/incidental
21-40   = mild
41-60   = moderate
61-80   = strong
81-100  = extreme/highly prominent

Intensity describes how strongly or prominently the
content appears in the post.

SEVERITY:

0       = absent
1-20    = minimal
21-40   = low
41-60   = moderate
61-80   = high
81-100  = extreme

Severity describes how serious or harmful the content is.

These are NOT probabilities.

Do not interpret them as confidence scores.

------------------------------------------------------------
SUBCATEGORY SCORING
------------------------------------------------------------

Every detected flag must contain one or more subcategories.

Each subcategory must contain:

name
intensity_percent

The subcategory intensity must be an integer from 0 to 100.

Only include subcategories that are actually present.

------------------------------------------------------------
CONTEXT
------------------------------------------------------------

The context stance must be exactly one of:

"endorsed"
"quoted"
"condemned"
"educational"
"fictional"
"descriptive"
"unclear"

endorsed:
The author appears to support, encourage, approve,
or promote the flagged content.

quoted:
The content is primarily quoted from another source.

condemned:
The author clearly criticizes, rejects, or condemns
the flagged content.

educational:
The content discusses the subject for educational,
academic, medical, or instructional purposes.

fictional:
The content occurs within fiction, storytelling,
roleplay, or an imagined scenario.

descriptive:
The author is neutrally describing an event or subject.

unclear:
The author's stance cannot reasonably be determined.

------------------------------------------------------------
CONTEXT RULES
------------------------------------------------------------

Analyze meaning and context rather than individual words.

A profanity word does not automatically mean the post
is vulgar in the relevant sense.

A sexual term in a medical or educational discussion
does not automatically mean the post is sexual content.

A quoted slur does not automatically mean the author
endorses the slur.

A post discussing violence does not necessarily promote
violence.

A fictional description should not automatically be
treated as a real-world threat.

Do not infer information that is not present.

A post can contain multiple flags simultaneously.

------------------------------------------------------------
OUTPUT RULES
------------------------------------------------------------

Return ONLY valid JSON.

Do not return markdown.

Do not return explanations.

Do not return comments.

Do not return additional fields.

Use this exact structure:

{json.dumps(self.output_example(), indent=4)}

If no sensitive content is detected:

{{
    "schema_version": "1.0",
    "flags": [],
    "context": {{
        "stance": "unclear"
    }}
}}
""".strip()

    # --------------------------------------------------------
    # USER MESSAGE
    # --------------------------------------------------------

    def user_message(self, post_data: str) -> str:

        if not isinstance(post_data, str):
            raise TypeError("post_data must be a string")

        post_data = post_data.strip()

        if not post_data:
            raise ValueError("post_data cannot be empty")

        return f"""
Analyze the following user-generated post.

<POST>
{post_data}
</POST>

Identify every applicable content flag using only the
allowed taxonomy provided in the system instructions.

Return JSON only.
""".strip()

    # --------------------------------------------------------
    # VALIDATE TAXONOMY
    # --------------------------------------------------------

    def validate_taxonomy(
        self,
        annotation: ContentSafetyAnnotation
    ) -> None:

        seen_flags = set()

        for flag in annotation.flags:

            # ----------------------------------------------
            # Validate flag name
            # ----------------------------------------------

            if flag.name not in self.flags:
                raise ValueError(
                    f"Unknown content flag: {flag.name}"
                )

            # ----------------------------------------------
            # Prevent duplicate flags
            # ----------------------------------------------

            if flag.name in seen_flags:
                raise ValueError(
                    f"Duplicate content flag: {flag.name}"
                )

            seen_flags.add(flag.name)

            # ----------------------------------------------
            # Validate subcategories
            # ----------------------------------------------

            allowed_subcategories = set(
                self.flags[flag.name]
            )

            seen_subcategories = set()

            for subcategory in flag.subcategories:

                if subcategory.name not in allowed_subcategories:
                    raise ValueError(
                        f"Unknown subcategory "
                        f"'{subcategory.name}' "
                        f"for flag '{flag.name}'"
                    )

                if subcategory.name in seen_subcategories:
                    raise ValueError(
                        f"Duplicate subcategory "
                        f"'{subcategory.name}' "
                        f"for flag '{flag.name}'"
                    )

                seen_subcategories.add(
                    subcategory.name
                )

            # ----------------------------------------------
            # Detected flags must contain subcategories
            # ----------------------------------------------

            if not flag.subcategories:
                raise ValueError(
                    f"Flag '{flag.name}' must contain "
                    "at least one subcategory"
                )

    # --------------------------------------------------------
    # PARSE RESPONSE
    # --------------------------------------------------------

    def parse(
        self,
        response: str
    ) -> ContentSafetyAnnotation:

        if not isinstance(response, str):
            raise TypeError(
                "AI response must be a string"
            )

        response = response.strip()

        if not response:
            raise ValueError(
                "AI response is empty"
            )

        # ----------------------------------------------
        # Remove accidental markdown fences
        # ----------------------------------------------

        if response.startswith("```json"):
            response = response[7:]

        elif response.startswith("```"):
            response = response[3:]

        if response.endswith("```"):
            response = response[:-3]

        response = response.strip()

        # ----------------------------------------------
        # Parse JSON
        # ----------------------------------------------

        try:

            data = json.loads(response)

        except json.JSONDecodeError as exc:

            raise ValueError(
                f"Invalid JSON returned by AI: {exc}"
            ) from exc

        # ----------------------------------------------
        # Pydantic validation
        # ----------------------------------------------

        try:

            annotation = (
                ContentSafetyAnnotation.parse_obj(data)
            )

        except ValidationError as exc:

            raise ValueError(
                f"Invalid content safety schema: {exc}"
            ) from exc

        # ----------------------------------------------
        # Taxonomy validation
        # ----------------------------------------------

        self.validate_taxonomy(annotation)

        return annotation

    # --------------------------------------------------------
    # SERIALIZE
    # --------------------------------------------------------

    def serialize(
        self,
        annotation: ContentSafetyAnnotation
    ) -> str:

        return annotation.json(
            ensure_ascii=False
        )

    # --------------------------------------------------------
    # DICT
    # --------------------------------------------------------

    def to_dict(
        self,
        annotation: ContentSafetyAnnotation
    ) -> dict:

        return annotation.dict()