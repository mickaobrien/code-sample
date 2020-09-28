from dateutil.relativedelta import relativedelta
from django.db import models
from django.utils import timezone
from enumfields import Enum, EnumIntegerField

from shared.models import AuditableModel


class Patient(AuditableModel):
    mrn = models.CharField(max_length=128, verbose_name='medical record number', primary_key=True)
    first_name = models.CharField(max_length=256, blank=True)
    last_name = models.CharField(max_length=256, blank=True)
    dob = models.DateField('date of birth', blank=True, null=True)
    approx_age = models.PositiveIntegerField('approx. age', blank=True, null=True)
    gender = EnumIntegerField(Gender, verbose_name='gender', default=Gender.UNKNOWN, blank=True, null=True)

    def __str__(self):
        return f'{self.first_name} {self.last_name} (MRN: {self.mrn})'

    @property
    def age(self):
        """ Calculate age using DOB if possible, else use the `approx_age` field
        """
        if self.dob:
            now = timezone.make_naive(timezone.localtime())
            return relativedelta(now, self.dob).years
        if self.approx_age:
            return self.approx_age
        return '?'

    @property
    def name(self):
        return f'{self.first_name} {self.last_name}'
