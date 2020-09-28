from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from enumfields import Enum, EnumIntegerField

from shared.models import AuditableModel, OrderableModel
from .speciality import Speciality


class QuestionType(Enum):
    BOOLEAN = 1
    TEXT = 2
    TIMESTAMP = 3
    NUMBER = 4
    CHOICE = 5
    LIST = 6
    LONG_TEXT = 7
    DATE = 8

    class Labels:
        BOOLEAN = 'boolean'
        TEXT = 'text'
        TIMESTAMP = 'timestamp'
        NUMBER = 'number'
        CHOICE = 'choice'
        LIST = 'list'
        LONG_TEXT = 'long_text'
        DATE = 'date'


class QuestionCategory(Enum):
    BACKGROUND = 1
    HISTORICAL_MEDS = 2
    DATA_CAPTURE = 3
    POSITIVES_NEGATIVES = 4
    GENERAL_EXAM = 5
    SOCIAL_HISTORY = 6
    DISCHARGE_PLAN = 7
    DIAGNOSIS_FEATURE = 8
    MDT = 9
    ISSUE_RESULT = 10

    class Labels:
        BACKGROUND = 'Background'
        HISTORICAL_MEDS = 'Historical medications'
        DATA_CAPTURE = 'Data capture'
        POSITIVES_NEGATIVES = 'Positives & Negatives'
        GENERAL_EXAM = 'General exam'
        SOCIAL_HISTORY = 'Social history'
        DISCHARGE_PLAN = 'Discharge plan'
        DIAGNOSIS_FEATURE = 'Diagnosis feature'
        MDT = 'MDT'
        ISSUE_RESULT = 'Issue result'


class Question(AuditableModel):
    title = models.CharField(max_length=256)
    speciality = models.ForeignKey(Speciality, on_delete=models.CASCADE)
    type = EnumIntegerField(QuestionType, default=QuestionType.BOOLEAN)
    category = EnumIntegerField(QuestionCategory)
    help_text = models.CharField(max_length=1000, blank=True, null=True)

    # The label is used to uniquely identify a Question (across all specialities) and is used
    # when getting data from  user created questions for charts, dashboards etc.
    label = models.SlugField(max_length=100, unique=True, blank=True, null=True)

    def __str__(self):
        return self.title


class QuestionGroup(OrderableModel, AuditableModel):
    """ A QuestionGroup is used to group Questions together and associate
        them with a parent object (Syndrome, Diagnosis, etc.) through a generic foreign key.
    """
    title = models.CharField(max_length=256, null=True, blank=True)
    category = EnumIntegerField(QuestionCategory)
    questions = models.ManyToManyField(
        Question,
        related_name='groups',
        through='OrderedQuestion',
        through_fields=('question_group', 'question'),
    )

    # Generic foreign key fields
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta(OrderableModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id', 'id'],
                condition=models.Q(category=QuestionCategory.ISSUE_RESULT),
                name='issues_can_only_have_one_question_group',
            )
        ]

    def __str__(self):
        return self.title or '(no title)'


class OrderedQuestion(OrderableModel, AuditableModel):
    """ A through model to allow questions to be ordered within a question group.
    """
    question_group = models.ForeignKey(QuestionGroup, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)

    class Meta(OrderableModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=['question', 'question_group'],
                name='questions_must_be_unique_within_a_question_group',
            )
        ]


class QuestionChoice(OrderableModel, AuditableModel):
    """ The options for choice/list questions.
    """
    title = models.CharField(max_length=256)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')

    def __str__(self):
        return self.title
