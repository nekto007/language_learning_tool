// Image preview for cover upload
    document.addEventListener('DOMContentLoaded', function() {
        const coverInput = document.getElementById('coverImageFile');
        const coverPreview = document.getElementById('coverPreview');
        const previewImg = document.querySelector('.preview-img');

        if (coverInput) {
            coverInput.addEventListener('change', function() {
                if (this.files && this.files[0]) {
                    const reader = new FileReader();

                    reader.onload = function(e) {
                        previewImg.src = e.target.result;
                        coverPreview.style.display = 'block';
                    }

                    reader.readAsDataURL(this.files[0]);
                }
            });
        }
    });
