(function () {
    const chartDays = window.PLAN_CHART_DAYS;
    const labels = chartDays.map(function (d) { return d.label; });
    const slotData = chartDays.map(function (d) { return d.slots_completed; });
    const colors = chartDays.map(function (d) {
        if (d.secured) return 'rgba(34, 197, 94, 0.8)';
        if (d.active) return 'rgba(99, 102, 241, 0.6)';
        return 'rgba(209, 213, 219, 0.4)';
    });

    const canvas = document.getElementById('planStatsChart');
    if (!canvas || typeof Chart === 'undefined') return;

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Слоты выполнено',
                data: slotData,
                backgroundColor: colors,
                borderRadius: 3,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function (ctx) {
                            const d = chartDays[ctx.dataIndex];
                            let suffix = '';
                            if (d.secured) suffix = ' (выполнен)';
                            else if (d.active) suffix = ' (начат)';
                            return ctx.parsed.y + ' слотов' + suffix;
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        maxRotation: 45,
                        minRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 10,
                        font: { size: 11 }
                    },
                    grid: { display: false }
                },
                y: {
                    beginAtZero: true,
                    ticks: { stepSize: 1, font: { size: 11 } },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                }
            }
        }
    });
})();
