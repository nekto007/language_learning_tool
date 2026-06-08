(function() {
        var btn = document.getElementById('importToggleBtn');
        var panel = document.getElementById('importPanel');
        if (btn && panel) {
            btn.addEventListener('click', function() {
                var expanded = btn.getAttribute('aria-expanded') === 'true';
                btn.setAttribute('aria-expanded', String(!expanded));
                panel.hidden = expanded;
            });
        }
    })();
