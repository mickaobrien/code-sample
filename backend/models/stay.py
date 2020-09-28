from django.db import models

from shared.models import AuditableModel

from .diagnosis import Diagnosis
from .doctor import Doctor
from .patient import Patient
from .syndrome import Syndrome

from ..querysets import NeurologyStayQuerySet


class Stay(AuditableModel):
    objects = models.Manager()
    # Custom manager that can be used to annotate Stays with Neurology specific data
    neurology_stays = NeurologyStayQuerySet.as_manager()

    active = models.BooleanField(default=True)
    admission_time = models.DateTimeField(blank=True, null=True)
    discharge_time = models.DateTimeField(blank=True, null=True)
    doctor = models.ForeignKey(Doctor, blank=True, null=True, related_name='stays', on_delete=models.SET_NULL)
    patient = models.ForeignKey(Patient, related_name='stays', on_delete=models.CASCADE)

    syndrome = models.ForeignKey(Syndrome, blank=True, null=True, on_delete=models.SET_NULL)
    diagnosis = models.ForeignKey(Diagnosis, blank=True, null=True, on_delete=models.SET_NULL)

    # An arbitrary 'Other' diagnosis can be store in `other_diagnosis_title`
    # At the API level, if other_diagnosis_selected = True then diagnosis is set to null
    other_diagnosis_title = models.CharField(max_length=256, blank=True, null=True)
    other_diagnosis_selected = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.id}: {self.patient.last_name}'

    def set_answer(self, question_id, answer=None, notes=None):
        """ Update the answer value and notes associated with question `question_id`.
        """
        stay_answer, _ = self.answers.get_or_create(question_id=question_id)
        if answer:
            stay_answer.set_value(answer)
        if notes:
            stay_answer.notes = notes
        stay_answer.save()

    @property
    def ward_round(self):
        """ Return the current WardRound object if there is an active one,
            else create a new one.
        """
        ward_round = self.wardround_set.last()
        if ward_round and not ward_round.complete:
            return ward_round

        return self.wardround_set.create()

    @property
    def diagnosis_title(self):
        if self.other_diagnosis_selected:
            return self.other_diagnosis_title
        if self.diagnosis:
            return self.diagnosis.title
