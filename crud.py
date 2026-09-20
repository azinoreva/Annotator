"""
Input / output / delete calls for every table in annotator.sqlite.

"Input"  = create a row
"Output" = read a row (by pk) or list rows (by filters)
"Delete" = delete a row (by pk) or by filters
"""

from typing import Any, Optional

from models.annotation_model import (
    Analysis,
    ProcessedAnnotation,
    ReceivedAnnotation,
    SentAnnotation,
    UnsentAnnotation,
)

# ---------------------------------------------------------------------------
# unsent_annotations
# ---------------------------------------------------------------------------

async def add_unsent_annotation(
    update_id: str,
    datetime: int,
    update_data: str,
    category: str,
    annotations: Any,
    user_id: str,
) -> UnsentAnnotation:
    return await UnsentAnnotation.create(
        update_id=update_id,
        datetime=datetime,
        update_data=update_data,
        category=category,
        annotations=annotations,
        user_id=user_id,
    )


async def get_unsent_annotation(update_id: str) -> Optional[UnsentAnnotation]:
    return await UnsentAnnotation.get_or_none(update_id=update_id)


async def list_unsent_annotations(**filters: Any) -> list[UnsentAnnotation]:
    return await UnsentAnnotation.filter(**filters).all()


async def delete_unsent_annotation(update_id: str) -> int:
    """Returns number of rows deleted (0 or 1)."""
    return await UnsentAnnotation.filter(update_id=update_id).delete()


# ---------------------------------------------------------------------------
# received_annotations
# ---------------------------------------------------------------------------

async def add_received_annotation(
    update_id: str,
    datetime: int,
    update_data: str,
    user_id: str,
    category: Optional[str] = None,
) -> ReceivedAnnotation:
    """Create the row, or leave it untouched if it already exists (idempotent)."""
    obj, _ = await ReceivedAnnotation.get_or_create(
        update_id=update_id,
        defaults={
            "datetime": datetime,
            "update_data": update_data,
            "category": category,
            "user_id": user_id,
        },
    )
    return obj


async def get_received_annotation(update_id: str) -> Optional[ReceivedAnnotation]:
    return await ReceivedAnnotation.get_or_none(update_id=update_id)


async def list_received_annotations(**filters: Any) -> list[ReceivedAnnotation]:
    return await ReceivedAnnotation.filter(**filters).all()


async def delete_received_annotation(update_id: str) -> int:
    return await ReceivedAnnotation.filter(update_id=update_id).delete()


# ---------------------------------------------------------------------------
# processed_annotations
# ---------------------------------------------------------------------------

async def add_processed_annotation(
    update_id: str,
    datetime: int,
    update_data: str,
    category: str,
    annotations: Any,
    user_id: str,
    morality: Optional[Any] = None,
) -> ProcessedAnnotation:
    """Create the row, or leave it untouched if it already exists (idempotent)."""
    obj, _ = await ProcessedAnnotation.get_or_create(
        update_id=update_id,
        defaults={
            "datetime": datetime,
            "update_data": update_data,
            "category": category,
            "annotations": annotations,
            "morality": morality,
            "user_id": user_id,
        },
    )
    return obj


async def get_processed_annotation(update_id: str) -> Optional[ProcessedAnnotation]:
    return await ProcessedAnnotation.get_or_none(update_id=update_id)


async def list_processed_annotations(**filters: Any) -> list[ProcessedAnnotation]:
    return await ProcessedAnnotation.filter(**filters).all()


async def delete_processed_annotation(update_id: str) -> int:
    return await ProcessedAnnotation.filter(update_id=update_id).delete()


# ---------------------------------------------------------------------------
# sent_annotations
# ---------------------------------------------------------------------------

async def add_sent_annotation(
    update_id: str,
    datetime: int,
    update_data: str,
    category: str,
    annotations: Any,
    user_id: str,
    morality: Optional[Any] = None,
) -> SentAnnotation:
    """Create the row, or leave it untouched if it already exists (idempotent)."""
    obj, _ = await SentAnnotation.get_or_create(
        update_id=update_id,
        defaults={
            "datetime": datetime,
            "update_data": update_data,
            "category": category,
            "annotations": annotations,
            "morality": morality,
            "user_id": user_id,
        },
    )
    return obj


async def get_sent_annotation(update_id: str) -> Optional[SentAnnotation]:
    return await SentAnnotation.get_or_none(update_id=update_id)


async def list_sent_annotations(**filters: Any) -> list[SentAnnotation]:
    return await SentAnnotation.filter(**filters).all()


async def delete_sent_annotation(update_id: str) -> int:
    return await SentAnnotation.filter(update_id=update_id).delete()


# ---------------------------------------------------------------------------
# analysis  (composite key: category_name + today)
# ---------------------------------------------------------------------------

async def upsert_analysis(
    category_name: str,
    today: str,
    frequency: int = 0,
) -> Analysis:
    """Set the frequency for the (category_name, today) row, creating it if needed."""
    obj, created = await Analysis.get_or_create(
        category_name=category_name,
        today=today,
        defaults={"frequency": frequency},
    )
    if not created:
        obj.frequency = frequency
        await obj.save(update_fields=["frequency"])
    return obj


async def increment_analysis(category_name: str, today: str) -> Analysis:
    """Bump the frequency count by 1 for a (category_name, today) row."""
    obj, created = await Analysis.get_or_create(
        category_name=category_name,
        today=today,
        defaults={"frequency": 1},
    )
    if not created:
        obj.frequency += 1
        await obj.save(update_fields=["frequency"])
    return obj


async def get_analysis(category_name: str, today: str) -> Optional[Analysis]:
    return await Analysis.get_or_none(category_name=category_name, today=today)


async def list_analysis(**filters: Any) -> list[Analysis]:
    return await Analysis.filter(**filters).all()


async def delete_analysis(category_name: str, today: str) -> int:
    return await Analysis.filter(category_name=category_name, today=today).delete()