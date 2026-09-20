"""
Tortoise ORM models for annotator.sqlite

Table -> Model mapping:
    unsent_annotations    -> UnsentAnnotation
    received_annotations  -> ReceivedAnnotation
    processed_annotations -> ProcessedAnnotation
    sent_annotations      -> SentAnnotation
    analysis              -> Analysis
"""

from tortoise import fields
from tortoise.models import Model


class UnsentAnnotation(Model):
    update_id = fields.CharField(pk=True, max_length=255)
    datetime = fields.IntField()
    update_data = fields.TextField()
    category = fields.CharField(max_length=255)
    annotations = fields.JSONField()
    user_id = fields.CharField(max_length=255)

    class Meta:
        table = "unsent_annotations"


class ReceivedAnnotation(Model):
    update_id = fields.CharField(pk=True, max_length=255)
    datetime = fields.IntField()
    update_data = fields.TextField()
    category = fields.CharField(max_length=255, null=True)
    user_id = fields.CharField(max_length=255)

    class Meta:
        table = "received_annotations"


class ProcessedAnnotation(Model):
    update_id = fields.CharField(pk=True, max_length=255)
    datetime = fields.IntField()
    update_data = fields.TextField()
    category = fields.CharField(max_length=255)
    annotations = fields.JSONField()
    morality = fields.JSONField(null=True)
    user_id = fields.CharField(max_length=255)

    class Meta:
        table = "processed_annotations"


class SentAnnotation(Model):
    update_id = fields.CharField(pk=True, max_length=255)
    datetime = fields.IntField()
    update_data = fields.TextField()
    category = fields.CharField(max_length=255)
    annotations = fields.JSONField()
    morality = fields.JSONField(null=True)
    user_id = fields.CharField(max_length=255)
    sent_at = fields.BigIntField(null=True)

    class Meta:
        table = "sent_annotations"


class Analysis(Model):
    # SQLite composite PK (category_name, today) -- Tortoise has no native
    # composite-PK support, so we use a surrogate `id` PK and enforce the
    # same uniqueness constraint via unique_together instead.
    id = fields.IntField(pk=True)
    category_name = fields.CharField(max_length=255)
    frequency = fields.IntField(default=0)
    today = fields.CharField(max_length=255)

    class Meta:
        table = "analysis"
        unique_together = (("category_name", "today"),)