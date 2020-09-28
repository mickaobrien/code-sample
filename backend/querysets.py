from datetime import timedelta

from django.apps import apps
from django.db import models
from django.db.models import (
    Case,
    Exists,
    F,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.fields import Field
from django.db.models.functions import TruncDate
from django.db.models.lookups import BuiltinLookup

from stays.helpers.question_labels import question_labels_to_type
from stays.helpers.stroke_diagnoses import STROKE_DIAGNOSES

from stays.models.care_classification import CareClassification, StayCareClassification
from stays.models.current_medication import TakingMedication
from stays.models.neurology import NBM
from stays.models.nihss import NIHSS
from stays.models.question import QuestionType
from stays.models.stage import Stage


class NeurologyStayQuerySet(models.QuerySet):
    """ A custom QuerySet to simplify accessing all Neurology/Stroke specific data.

        It has several helper methods that annotate a a stay queryset with stroke specific data
        as well as some helpful filter methods. A lot of the data is based on user defined input
        (questions, diagnosis titles etc.) and the idea here is to standardise how it's accessed
        to make the system more robust.

        It's added as a custom manager to the `Stay` model.

        Example usage:
        stays = (
            Stay
            .neurology_stays
            .stroke_stays()
            .with_correct_meds_data()
            .exclude_transferred_back()
        )
    """
    def stroke_stays(self):
        """ Filter stays so that only stays with an explicit Stroke diagnosis are returned.
        """
        return self.filter(
            Q(syndrome__title='Stroke', other_diagnosis_selected=False) &
            Q(diagnosis__title__in=STROKE_DIAGNOSES)
        )

    def with_questions(self, **kwargs):
        """ This is a helper to allow us to annotate the queryset with answers to multiple questions
            without having to write `question_answers(question_label)` over and over.

            The `kwargs` are in the from `field=question_label` e.g. `atrial_fibrillation='nel-atrial-fibrillation'`
            and we use the `question_answer` method to generate the right subquery based on the label
            i.e. convert it to `atrial_fibrillation=question_answer('nel-atrial-fibrillation')`
        """
        fields = {field: question_answer(question_label) for (field, question_label) in kwargs.items()}
        return self.annotate(**fields)

    def with_correct_meds_data(self):
        """ Annotate the queryset with the `on_correct_meds` value. This value only makes sense for stroke stays.

            The logic used is as follows:
                - ischaemic stroke with AF should be on anticoagulants, antihypertensives and statins
                - ischaemic stroke without AF should be on antihypertensives, antithrombotics and statins
                - Intracerebral haemorrhage should be on antihypertensives and not be on antithrombotics
        """

        StayBaselineInvestigationResult = apps.get_model('stays', 'StayBaselineInvestigationResult')
        StayCurrentMedication = apps.get_model('stays', 'StayCurrentMedication')
        StayInvestigationResult = apps.get_model('stays', 'StayInvestigationResult')

        def on_med_category(category_title):
            """ Return an `Exists` subquery to check if the stay is on a current medication
                or it's been contraindicated.
            """
            return Exists(
                StayCurrentMedication
                .objects
                .filter(
                    stay_id=OuterRef('id'),
                    medication__category__title__iexact=category_title,
                    medication__taking__in=[TakingMedication.YES, TakingMedication.CONTRAINDICATED],
                )
            )

        return self.annotate(
            # Annotate with all possible sources of "has AF" for a stay
            #     - answer to a Background question
            #     - results from a baseline ECG
            #     - results from a non-baseline ECG
            #     - results from a holter monitor investigation
            af_background_answer=question_answer('nel-atrial-fibrillation'),
            af_diagnosed_in_standard_ecg=Exists(
                StayInvestigationResult
                .objects
                .filter(
                    stay_id=OuterRef('id'),
                    investigation__title='ECG',
                    results__title__iexact='atrial fibrillation'
                )
            ),
            af_diagnosed_in_baseline_ecg=Exists(
                StayBaselineInvestigationResult
                .objects
                .filter(
                    stay_id=OuterRef('id'),
                    investigation__title='ECG',
                    results__title__iexact='atrial fibrillation'
                )
            ),
            af_diagnosed_in_holter_investigation=Exists(
                StayInvestigationResult
                .objects
                .filter(
                    stay_id=OuterRef('id'),
                    investigation__title='Holter monitor',
                    results__title__iexact='atrial fibrillation documented'
                )
            ),
            # Combine all the atrial fibrillation sources into one `has_af` annotation
            has_af=Case(
                When(af_background_answer__iexact='Yes', then=Value(True)),
                When(af_background_answer__iexact='New diagnosis', then=Value(True)),
                When(af_diagnosed_in_standard_ecg=True, then=Value(True)),
                When(af_diagnosed_in_baseline_ecg=True, then=Value(True)),
                When(af_diagnosed_in_holter_investigation=True, then=Value(True)),
                default=Value(False),
                output_field=models.BooleanField()
            ),
            on_anticoagulants=on_med_category('anticoagulation therapy status'),
            on_antihypertensives=on_med_category('antihypertensive therapy'),
            on_antiplatelets=on_med_category('antiplatelet therapy status'),
            on_statins=on_med_category('statin therapy'),
            on_antithrombotics=(Case(
                When(on_anticoagulants=True, then=Value(True)),
                When(on_antiplatelets=True, then=Value(True)),
                default=Value(False),
                output_field=models.BooleanField(),
            )),
            not_on_antithrombotics=(~Exists(
                StayCurrentMedication
                .objects
                .filter(
                    Q(medication__category__title__iexact='anticoagulation therapy status') |
                    Q(medication__category__title__iexact='antiplatelet therapy status'),
                    stay_id=OuterRef('id'),
                    medication__taking=TakingMedication.YES
                )
            )),
            # Annotate with the "on correct meds" value based on the stay's diagnosis
            # and the meds they're taking
            on_correct_meds=(Case(
                When(
                    diagnosis__title__icontains='ischaemic stroke',
                    has_af=True,
                    on_anticoagulants=True,
                    on_antihypertensives=True,
                    on_statins=True,
                    then=Value(True),
                ),
                When(
                    diagnosis__title__icontains='ischaemic stroke',
                    has_af=False,
                    on_antihypertensives=True,
                    on_antithrombotics=True,
                    on_statins=True,
                    then=Value(True),
                ),
                When(
                    diagnosis__title='Intracerebral haemorrhage',
                    not_on_antithrombotics=True,
                    on_antihypertensives=True,
                    then=Value(True),
                ),
                default=Value(False),
                output_field=models.BooleanField(),
            )),
        )

    def with_hyperacute_report_data(self):
        # TODO new /hyperacute-status endpoint that pulls in the data as necessary?
        return self.with_questions(
            doctors_involved='nel-doctors-involved',
            presentation_type='nel-presentation-type',
            hyperacute_review='nel-hyperacute-review',
            local_site_doctor_used_asap='nel-local-site-doctor-used-asap',
            first_contact_made_prior_to_ct='nel-first-contact-made-prior-to-patient-going-to-ct',
            reasons_not_thrombolysed='nel-reasons-not-thrombolysed',
            other_reasons_not_given_thrombolysis='nel-other-reasons-not-given-thrombolysis',
            reasons_not_sent_for_ecr='nel-reasons-not-sent-for-ecr',
            other_reasons_not_sent_for_ecr='nel-other-reasons-not-sent-for-ecr',
            time_of_first_neurology_contact='nel-time-of-first-nel-contact',
            time_of_acute_imaging_starting='nel-time-of-acute-imaging-starting',
            time_of_lysis_treatment_decision='nel-time-of-lysis-treatment-decision',
            # TODO "Door to ..." times can't be annotated like
            #      door_to_alert = F('time_of_first_neurology_contact') - F('admission_time')
            #      due to this Django bug: https://code.djangoproject.com/ticket/31133
        ).annotate(
            needle_time=F('thrombolysis__bolus_time'),
            last_seen_well=F('presentation__last_seen_well'),
            last_seen_well_time=F('presentation__lsw_time'),
        ).prefetch_related(
            Prefetch('nihss_set', queryset=NIHSS.objects.filter(stage=Stage.ADMISSION))
        )

    def with_stroke_data(self):
        """ Annotate the queryset with all the data points that are of interest for stroke care.
            These values are used in generating the Hyperacute report card, in the stroke charts,
            and in the data viz.
        """
        return self.with_questions(
            doctors_involved='nel-doctors-involved',
            presentation_type='nel-presentation-type',
            hyperacute_review='nel-hyperacute-review',
            time_of_first_neurology_contact='nel-time-of-first-nel-contact',
            time_of_acute_imaging_starting='nel-time-of-acute-imaging-starting',
            time_of_lysis_treatment_decision='nel-time-of-lysis-treatment-decision',
            reasons_not_thrombolysed='nel-reasons-not-thrombolysed',
            other_reasons_not_given_thrombolysis='nel-other-reasons-not-given-thrombolysis',
            reasons_not_sent_for_ecr='nel-reasons-not-sent-for-ecr',
            other_reasons_not_sent_for_ecr='nel-other-reasons-not-sent-for-ecr',
            reviewed_by_stroke_nurse_in_ed='nel-reviewed-by-stroke-nurse-in-ed',
            time_transferred_out_of_ed='nel-time-transferred-out-of-ed',
            local_site_doctor_used_asap='nel-local-site-doctor-used-asap',
            swallow_status='nel-swallow-status',
            my_stroke_journey_given='nel-my-stroke-journey-given',
            follow_up_nihss='nel-follow-up-nihss',
            infectious_contact_precautions='nel-infectious-contact-precautions',
            reg_present_at_time_of_patient_arrival='nel-reg-present-at-time-of-patient-arrival',
            first_contact_made_prior_to_ct='nel-first-contact-made-prior-to-patient-going-to-ct',
            time_of_ecr_treatment_decision='nel-time-of-ecr-treatment-decision',
            admitted_to_icu='nel-admitted-to-icu',
            days_in_icu='nel-days-in-icu',
            admitted_to_ccu='nel-admitted-to-ccu',
            days_in_ccu='nel-days-in-ccu',
            transferred_back_gt_1week_onset='nel-transferred-gt-1week-onset',
            transferred_to_other_center='nel-transferred-to-other-center',
        ).annotate(
            needle_time=F('thrombolysis__bolus_time'),
            is_lysis=F('diagnosis__is_thrombolysis'),
        )

    def with_stroke_unit_data(self):
        Location = apps.get_model('stays', 'Location')

        return (
            self
            .with_questions(
                # Annotate with Data Capture answers that are relevant to stroke unit access
                admitted_to_icu='nel-admitted-to-icu',
                days_in_icu='nel-days-in-icu',
                admitted_to_ccu='nel-admitted-to-ccu',
                days_in_ccu='nel-days-in-ccu',
            )
            .annotate(
                # Admitted to the stroke unit if the stay has been in a stroke bed
                admitted_to_stroke_unit=Exists(
                    Location.objects.filter(stay_id=OuterRef('id'), is_stroke_bed=True),
                ),
                # We count a stay as having had adequate access to the stroke unit if:
                #    - the stay was admitted to the stroke unit or
                #    - the stay was admitted to the ICU and spent >0 days there or
                #    - the stay was admitted to the CCU and spent >0 days there
                spent_time_in_su_icu_or_ccu=(
                    Case(
                        When(admitted_to_icu=True, days_in_icu__gt=0, then=Value(True)),
                        When(admitted_to_ccu=True, days_in_ccu__gt=0, then=Value(True)),
                        When(admitted_to_stroke_unit=True, then=Value(True)),
                        default=Value(False),
                        output_field=models.BooleanField()
                    )
                ),
            )
        )

    def with_nbm_data(self):
        return (
            self.annotate(
                nbm_good=Case(
                    When(
                        neurology_fields__nbm__in=[NBM.NBM_UNTIL_SPEECH_PATH, NBM.NBM_UNTIL_ASSIST_CLEARANCE],
                        then=Value(True)
                    ),
                    default=Value(False),
                    output_field=models.BooleanField()
                ),
            )
        )

    def exclude_transferred_back(self):
        return (
            self.with_questions(
                transferred_back_gt_1week_onset='nel-transferred-gt-1week-onset',
                transferred_to_other_center='nel-transferred-to-other-center',
            )
            .exclude(
                Q(transferred_back_gt_1week_onset__isnull=False) &
                Q(transferred_back_gt_1week_onset=True)
            )
            .exclude(
                Q(transferred_to_other_center__isnull=False) &
                Q(transferred_to_other_center=True)
            )
        )

    def exclude_isolated_for_infectious_contact_precautions(self):
        return (
            self
            .with_questions(
                infectious_contact_precautions='nel-infectious-contact-precautions',
            )
            .exclude(
                Q(infectious_contact_precautions__isnull=False) &
                Q(infectious_contact_precautions=True),
            )
        )

    def exclude_palliative(self):
        """ Exclude Stays that are currently marked palliative
        """
        return (
            self
            .annotate(
                current_care_classification=Subquery(
                    StayCareClassification
                    .objects
                    .filter(
                        stay_id=OuterRef('id')
                    )
                    .order_by('-date')
                    [:1]
                    .values('classification')
                ),
            )
            .exclude(
                Q(current_care_classification__isnull=False) &
                Q(current_care_classification=CareClassification.PALLIATIVE_PATHWAY),
            )
        )

    def exclude_palliative_in_first_24_hours(self):
        return (
            self
            .annotate(
                # `admission_date` is used for checking if care classification=PALLIATIVE_PATHWAY in first 24 hours
                # TruncDate preserves the timezone
                admission_date=TruncDate('admission_time'),
                # Palliative in the 1st 24 hours if the stay has a palliative care classification
                # that was set on the day of admission or the next day
                palliative_in_first_24_hours=Exists(
                    StayCareClassification
                    .objects
                    .filter(
                        stay_id=OuterRef('id'),
                        classification=CareClassification.PALLIATIVE_PATHWAY,
                        date__lte=OuterRef('admission_date') + timedelta(days=1),
                    )
                )
            )
            .exclude(
                Q(palliative_in_first_24_hours__isnull=False) &
                Q(palliative_in_first_24_hours=True),
            )
        )


class Any(BuiltinLookup):
    """ Custom database lookup for Postgres' `ANY` lookup
        Postgres docs: https://www.postgresql.org/docs/9.1/arrays.html
        e.g. `SELECT * FROM sal_emp WHERE 10000 = ANY (pay_by_quarter);`
             returns all rows when any value in `pay_by_quarter` is 10000

        We use it to get QuestionChoices associated with an answer. The answer stores the
        list of IDs in an array and we filter QuestionChoices against this array to get the selected
        choices and their titles.
    """
    lookup_name = 'any'

    def get_rhs_op(self, connection, rhs):
        return ' = ANY(%s)' % (rhs,)


Field.register_lookup(Any)


class Array(Subquery):
    """ Custom Subquery to return multiple values as an array. We use it to get
        all question titles associated with a QuestionType.LIST question i.e.
        where a user can select more than one choice.
    """
    template = 'ARRAY(%(subquery)s)'


def question_answer(question_label):
    """ Return a subquery that will get the answer for the stay for the question with the
        specified `question_label`.

        Example usage:
            Stay.objects.annotate(
                admitted_to_icu=question_answer('nel-admitted-to-icu')
            )
    """
    question_type = question_labels_to_type[question_label]
    if question_type == QuestionType.LIST:
        return list_q(question_label)
    elif question_type == QuestionType.CHOICE:
        return choice_q(question_label)
    return generic_q(question_label, question_type)


def generic_q(label, type):
    """ Annotate the stay with the value selected for the question with label == `label`.
    """
    StayAnswer = apps.get_model('stays', 'StayAnswer')
    type_label_dict = {number: label for number, label in QuestionType.CHOICES}
    type_label = type_label_dict[type]
    return Subquery(
        StayAnswer
        .objects
        .filter(stay_id=OuterRef('id'), question__label=label)
        .values(f'{type_label}_value')[:1]
    )


def choice_q(label):
    """ Annotate the stay with the title of the choice selected for the stay for the answer to the
        question with label == `label`.
    """
    StayAnswer = apps.get_model('stays', 'StayAnswer')
    QuestionChoice = apps.get_model('stays', 'QuestionChoice')
    return Subquery(
        StayAnswer
        .objects
        .filter(
            stay_id=OuterRef('id'),
            question__label=label,
        )
        .annotate(
            ct=(
                Subquery(
                    QuestionChoice
                    .objects
                    .filter(
                        question_id=OuterRef('question_id'),
                        id=OuterRef('choice_value')
                    )
                    .values('title')
                    [:1]
                )
            )
        )
        .values('ct')
        [:1],
        output_field=models.CharField()
    )


def list_q(label):
    """ Annotate the stay with an array containing the titles of all choices selected
        for the stay.
    """
    StayAnswer = apps.get_model('stays', 'StayAnswer')
    QuestionChoice = apps.get_model('stays', 'QuestionChoice')
    return Subquery(
        StayAnswer
        .objects
        .filter(
            stay_id=OuterRef('id'),
            question__title=label,
        )
        .annotate(
            selected_choice_titles=(
                Array(
                    QuestionChoice
                    .objects
                    .filter(
                        question_id=OuterRef('question_id'),
                        id__any=OuterRef('list_value'),
                    )
                    .values('title'),
                )
            )
        )
        .values('selected_choice_titles')
        [:1],
        output_field=models.CharField()
     )
