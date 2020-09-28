from django.db import models

from shared.models import AuditableModel
from .base.answer import AnswerBase
from .question import Question, QuestionChoice


class StayAnswer(AnswerBase, AuditableModel):
    """ A model for a stay's answers to questions.
    """
    stay = models.ForeignKey('Stay', on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    notes = models.TextField(blank=True, null=True)

    # All possible value types
    boolean_value = models.NullBooleanField(blank=True)
    text_value = models.TextField(blank=True, null=True)
    timestamp_value = models.DateTimeField(null=True, blank=True)
    date_value = models.DateField(null=True, blank=True)
    number_value = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    choice_value = models.ForeignKey(QuestionChoice, blank=True, null=True, on_delete=models.PROTECT)
    list_value = models.ManyToManyField(QuestionChoice, blank=True)

    class Meta:
        unique_together = ('stay', 'question')

    @property
    def _value_field(self):
        """ Returns the name of the field where the answer is stored based on the question type.
            e.g. for a question with type=QuestionType.BOOLEAN, returns `boolean_value`
        """
        type_str = self.question.get_type_display()

        # Map all text fields to the `text_value` column
        if type_str in ('text', 'long_text'):
            type_str = 'text'

        return f'{type_str}_value'

    @property
    def value(self):
        return getattr(self, self._value_field)

    def set_value(self, value):
        value_field = self._value_field

        if value_field == 'list_value':
            # Update the ManyToMany choice relationship using `list_value.set`
            self.list_value.set(value)

        else:
            # Update standard fields using `setattr`
            setattr(self, self._value_field, value)
