(function () {
    const tooltip = document.getElementById('calTooltip');
    const cells = document.querySelectorAll('.plan-calendar__cell[data-date]');

    cells.forEach(function (cell) {
        cell.addEventListener('mouseenter', function (e) {
            const label = cell.dataset.label;
            const secured = cell.dataset.secured === 'true';
            const level = parseInt(cell.className.match(/level-(\d)/)?.[1] ?? '0');
            let text = label;
            if (secured) text += ' — план выполнен';
            else if (level === 1) text += ' — начат';
            tooltip.textContent = text;
            tooltip.style.display = 'block';
        });
        cell.addEventListener('mousemove', function (e) {
            tooltip.style.left = (e.clientX + 12) + 'px';
            tooltip.style.top = (e.clientY - 28) + 'px';
        });
        cell.addEventListener('mouseleave', function () {
            tooltip.style.display = 'none';
        });
    });
})();
