document.addEventListener('DOMContentLoaded', function() {
    const coverInput = document.getElementById('coverInput');
    const fileInfo = document.getElementById('fileInfo');
    const coverPreview = document.getElementById('coverPreview');

    if (coverInput) {
        coverInput.addEventListener('change', function() {
            if (this.files && this.files[0]) {
                const file = this.files[0];
                const fileName = file.name;
                const fileSize = Math.round(file.size / 1024);

                fileInfo.textContent = `${fileName} (${fileSize} ${window.I18N_KB})`;
                fileInfo.style.display = 'block';

                // Preview the selected image
                const reader = new FileReader();
                reader.onload = function(e) {
                    let img = coverPreview.querySelector('.eic-cover__img');
                    const placeholder = coverPreview.querySelector('.eic-cover__placeholder');

                    if (placeholder) {
                        placeholder.style.display = 'none';
                    }

                    if (!img) {
                        img = document.createElement('img');
                        img.className = 'eic-cover__img';
                        img.id = 'coverImg';
                        coverPreview.appendChild(img);
                    }

                    img.src = e.target.result;
                    img.alt = fileName;
                };
                reader.readAsDataURL(file);
            }
        });
    }
});
