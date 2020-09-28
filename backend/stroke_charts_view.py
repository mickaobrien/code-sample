import calendar

from django.db.models import (
    Count,
    Q,
)
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.utils import timezone
from django.views import View

from stays.models import Stay


class StrokeChartDataView(View):
    def get(self, request):
        """ Returns all data necessary to draw charts for breakdown of stroke cases, month by month in the year to date.
        """
        now = timezone.localtime()

        # Get the first stay of the year to exclude earlier months when the system wasn't running
        first_stay = (
            Stay
            .objects
            .filter(admission_time__year=now.year)
            .order_by('admission_time')
            .first()
        )
        if first_stay:
            first_start_time = first_stay.admission_time
            if first_start_time.year == now.year:
                first_month = first_start_time.month

        # List of month names in year to date, used as labels on the front end
        months = [calendar.month_name[i] for i in range(first_month or 1, now.month + 1)]

        # Add in the stroke unit access data
        stroke_unit_access_data, stroke_unit_access_percentage = self.stroke_unit_access_data()
        data = {
            'months': months,
            'stroke_unit_access': stroke_unit_access_data,
            'stroke_unit_access_percentage': stroke_unit_access_percentage,
        }

        return JsonResponse(data)

    def stroke_unit_access_data(self):
        """ Returns a tuple of the list of percentages of stays that had appropriate access to the stroke unit
            and the year to date percentage.
            Each entry in the list corresponds to a month in the year to date: e.g. [71.5, 95.2, ...]

            We look at all stroke stays and exclude stays that were:
                - made palliative in the first 24 hours,
                - isolated for infectious contact precautions,
                - transferred back to the hospital > 1 week after stroke onset,
                - transferred out of the hospital and did not return,
        """
        now = timezone.localtime()

        valid_annotated_stays = (
            Stay
            .neurology_stays
            .filter(admission_time__year=now.year)
            .stroke_stays()
            .with_stroke_unit_data()
            .exclude_palliative_in_first_24_hours()
            .exclude_transferred_back()
            .exclude_isolated_for_infectious_contact_precautions()
        )

        # Group stays by month and count the number who `spent_time_in_su_icu_or_ccu` and the total
        access_to_su_counts = (
            valid_annotated_stays
            .annotate(month=TruncMonth('admission_time'))
            .values('month')
            .annotate(
                had_access_count=Count('id', filter=Q(spent_time_in_su_icu_or_ccu=True)),
                total=Count('id'),
                # ids=ArrayAgg('id'),  # Useful for debugging
            )
            .order_by('month')
        )

        # Create a list of length $NUMBER_OF_MONTHS_SO_FAR_THIS_YEAR
        stroke_counts_by_month = [None] * now.month

        # Calculate the percentage of stays that had stroke unit access each month
        for entry in access_to_su_counts:
            index = entry['month'].month - 1
            stroke_counts_by_month[index] = round(entry['had_access_count']*100/entry['total'], 1)

        # Calculate the year to date percentage
        total_access_count = sum([d['had_access_count'] for d in access_to_su_counts])
        total_count = sum([d['total'] for d in access_to_su_counts])
        year_to_date_percentage = round((total_access_count*100/total_count) if total_count > 0 else 0, 1)

        return stroke_counts_by_month, year_to_date_percentage
