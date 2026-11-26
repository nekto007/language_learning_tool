(() => {
    'use strict';

    const key = 'llt:reader-appearance-v1';
    const defaults = {size: 18, font: 'serif', spacing: 'normal', width: 'normal', theme: 'light'};
    const root = document.documentElement;
    const controls = [...document.querySelectorAll('[data-reader-setting]')];
    const themes = [...document.querySelectorAll('[name="reader-theme"]')];
    const sizeValue = document.getElementById('reader-size-value');

    function readPreferences() {
        try {
            const stored = JSON.parse(localStorage.getItem(key));
            return stored ?? {
                size: localStorage.getItem('readerFontSize') ?? defaults.size,
                theme: localStorage.getItem('readerDarkTheme') === 'true' ? 'dark' : 'light',
            };
        } catch (_) {
            return {};
        }
    }

    function render(candidate) {
        const values = {...defaults};
        for (const control of controls) {
            const name = control.dataset.readerSetting;
            const value = String(candidate[name]);
            if (name === 'size') {
                const size = Number(value);
                if (Number.isInteger(size) && size >= +control.min && size <= +control.max) values.size = size;
            } else if ([...control.options].some(option => option.value === value)) {
                values[name] = value;
            }
            control.value = values[name];
        }
        if (themes.some(theme => theme.value === candidate.theme)) values.theme = candidate.theme;
        for (const theme of themes) theme.checked = theme.value === values.theme;
        sizeValue.value = values.size + ' px';
        window.readerReflow(() => {
            root.style.setProperty('--reader-size', values.size + 'px');
            root.dataset.readerFont = values.font;
            root.dataset.readerSpacing = values.spacing;
            root.dataset.readerWidth = values.width;
            root.dataset.readerTheme = values.theme;
        });
        return values;
    }

    function update(values) {
        const current = render(values);
        try { localStorage.setItem(key, JSON.stringify(current)); } catch (_) {}
    }

    render(readPreferences());
    for (const control of [...controls, ...themes]) {
        control.addEventListener('input', () => {
            const values = Object.fromEntries(controls.map(item => [item.dataset.readerSetting, item.value]));
            values.theme = themes.find(theme => theme.checked)?.value;
            update(values);
        });
    }
    document.getElementById('reader-reset').addEventListener('click', () => update(defaults));

    for (const trigger of document.querySelectorAll('[data-reader-panel]')) {
        const dialog = document.getElementById(trigger.dataset.readerPanel);
        trigger.addEventListener('click', () => {
            dialog.showModal();
            const current = dialog.querySelector('[aria-current], input');
            if (current) {
                current.focus({preventScroll: true});
                current.scrollIntoView({block: 'nearest'});
            }
        });
        dialog.querySelector('[data-reader-close]').addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', () => {
            // Native dialog restores its opener. Use a fallback only if focus
            // stayed inside or returned to the document body.
            if (dialog.contains(document.activeElement) || document.activeElement === document.body) {
                trigger.focus({preventScroll: true});
            }
        });
        dialog.addEventListener('click', event => {
            if (event.target !== dialog) return;
            const box = dialog.getBoundingClientRect();
            if (event.clientX < box.left || event.clientX > box.right ||
                event.clientY < box.top || event.clientY > box.bottom) dialog.close();
        });
    }
})();
