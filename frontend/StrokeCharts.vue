<template>
    <div class="row mt-4">
        <div class="col-12 col-lg-6">
            <p class="text-center mt-2 mb-0">
                Stroke unit access
            </p>
            <p v-if="data" class="text-center mt-0 mb-2">
                Year to date: {{ data.stroke_unit_access_percentage }}%
            </p>
            <canvas class="mt-2 mb-4" ref="strokeUnitAccessChart"></canvas>
        </div>
    </div>
</template>

<script lang="ts">
import Vue from 'vue'

import { Chart, PositionType } from 'chart.js'
import { debounce, isInteger } from 'lodash-es'

import utils from 'utils'

import userprofile from '@store/userprofile'

// Expected structure of data received from server
interface ChartData {
    months: string[]
    total_sites: number
    ischaemic_stroke: number[]
    ich: number[]
    other: number[]
    lysed_only: number[]
    ecr_only: number[]
    lysed_and_ecr: number[]
    door_to_alert_times: number[]
    door_to_ct_times: number[]
    door_to_lysis_decision_times: number[]
    door_to_ecr_decision_times: number[]
    door_to_needle_times: {date: string, time_in_minutes: number}[]
    door_to_needle_median: number
    discharged_on_correct_meds: number[]
    stroke_unit_access: number[]
    stroke_unit_access_percentage: number
    nbm_data: number[]
    nbm_percentage: number
    discharged_on_correct_meds_percentage: number
}

export default Vue.extend({
    data() {
        return {
            data: null as ChartData | null,
            loading: false,
            charts: {} as {[k: string]: Chart},
        }
    },
    created() {
        this.fetchData()
    },
    methods: {
        fetchData() {
            this.loading = true
            return utils
                .request
                .get('/stroke-chart-data/', { hospitals: this.hospitals })
                .then(response => {
                    this.data = response.body
                    this.loading = false
                    this.renderCharts()
                })
                .catch(err => {
                    utils.handleRequestError(err)
                })
        },
        renderCharts() {
            if (!this.data) return

            const barStyling = {
                minBarLength: 2,
            }

            const legendSettings = {
                display: true,
                labels: {
                    fontColor: 'white',
                    fontSize: 14,
                },
                position: 'bottom' as any,
            }

            const fontStyling = {
                fontColor: 'white',
                fontSize: 14,
            }

            const yTicks = {
                beginAtZero: true,
                callback: function(value: number) {
                    if (isInteger(value)) { return value }
                    return ''
                },
                ...fontStyling,
                stepSize: 1,
                min: 0,
            }

            const yAxes = [
                {
                    scaleLabel: {
                        display: true,
                        ...fontStyling,
                        fontColor: '#ccc',
                        labelString: 'Stays',
                    },
                    ticks: yTicks,
                },
            ]

            const xAxes = [
                {
                    ticks: {
                        ...fontStyling,
                    },
                },
            ]

            const options = {
                legend: legendSettings,
                scales: {
                    xAxes,
                    yAxes,
                },
            }

            if (!this.charts) return

            const lineStyles = {
                borderColor: '#4472c4',
                backgroundColor: '#a5a5a5',
                lineTension: 0.1,
                fill: false,
            }

            const percentageLineOptions = {
                legend: { display: false },
                scales: {
                    xAxes: [
                        {
                            ticks: { ...fontStyling },
                        },
                    ],
                    yAxes: [
                        {
                            scaleLabel: {
                                display: true,
                                labelString: '%',
                                ...fontStyling,
                            },
                            ticks: {
                                min: 0,
                                max: 100,
                                ...fontStyling
                            },
                        },
                    ]
                },
                    tooltips: {
                        callbacks: {
                            label: (tooltipItem: { xLabel: string, yLabel: string }) => {
                                return `${tooltipItem.yLabel}%`
                            }
                        },
                    },
            }

            // Stroke unit access
            this.updateChart({
                title: 'strokeUnitAccessChart',
                chartType: 'line',
                data: {
                    labels: this.data.months,
                    datasets: [
                        {
                            label: 'Percentage',
                            data: this.data.stroke_unit_access,
                            ...lineStyles,
                        },
                    ],
                },
                options: percentageLineOptions,
            })

        },
        updateChart({title, data, options, chartType}: {title: string, data: object, options: object, chartType: string}) {
            // Try and get the chart object stored in this.charts
            let chart = this.charts[title]
            if (!chart) {
                // If it doesn't exist we try and create it.
                // If there's no matching $ref we ignore it
                // (this happens e.g. for a chart shown only in telestroke mode when we're in non-telestroke mode)
                if (!this.$refs[title]) return

                // Create the new Chart and store it in this.charts
                this.charts[title] = new Chart(this.$refs[title] as any, { type: chartType })
                chart = this.charts[title]
            }
            chart.data = data
            chart.options = options
            chart.update()
        },
    },
    computed: {
        // The debounced function needs to be a `computed` property to work properly
        debouncedFetchData: function(): any {
            return debounce(this.fetchData, 1000, {leading: true})
        },
    },
})
</script>
