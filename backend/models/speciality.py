from django.apps import apps
from django.db import models

from shared.models import AuditableModel
from .investigation import InvestigationStatus, InvestigationStatusLabel
from .people_present import PeoplePresent
from .mixins.has_question_groups import HasQuestionGroupsMixin


class Speciality(AuditableModel, HasQuestionGroupsMixin):
    title = models.CharField(max_length=256)
    code = models.CharField(max_length=128, unique=True, blank=True)

    class Meta:
        verbose_name_plural = 'Specialities'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Add default data to a new speciality if `add_initial_data=False` is not specified
        is_new = not self.pk
        add_initial_data = kwargs.pop('add_initial_data', True)

        super().save(*args, **kwargs)

        if is_new and add_initial_data:
            self._add_default_data()

    def _add_default_data(self):
        people_present = [
            'Patient',
            'Husband',
            'Wife',
            'Son',
            'Daughter',
            'Mother',
            'Father',
            'Family',
        ]
        PeoplePresent.objects.bulk_create([
            PeoplePresent(title=person, speciality=self) for person in people_present
        ])

        investigation_statuses = [
            {'title': 'Required', 'status': InvestigationStatus.REQUIRED},
            {'title': 'Ordered', 'status': InvestigationStatus.ORDERED},
            {'title': 'Done', 'status': InvestigationStatus.DONE},
            {'title': 'Follow up with GP', 'status': InvestigationStatus.OUTPATIENT},
        ]
        InvestigationStatusLabel.objects.bulk_create([
            InvestigationStatusLabel(speciality=self, **status) for status in investigation_statuses
        ])

        follow_up_time_options = [
            '<undecided>',
            '2 weeks',
            '4 weeks',
            '6 weeks',
            '3 months',
        ]

        # Use apps.get_model to avoid circular import issues
        FollowUpTime = apps.get_model('stays', 'FollowUpTime')
        FollowUpTime.objects.bulk_create([
            FollowUpTime(speciality=self, title=title, order=i) for (i, title) in enumerate(follow_up_time_options)
        ])
