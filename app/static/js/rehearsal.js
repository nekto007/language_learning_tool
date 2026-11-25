(() => {
    const action = document.getElementById('seller-audio');
    const line = document.getElementById('seller-line');
    const status = document.getElementById('voice-status');
    if (!action || !line || !status || !window.speechSynthesis || !window.SpeechSynthesisUtterance) return;

    const synth = window.speechSynthesis;
    let voice;
    function updateVoice() {
        const localEnglish = synth.getVoices().filter(candidate => candidate.localService && /^en(?:[-_]|$)/i.test(candidate.lang));
        voice = localEnglish.find(candidate => candidate.default) || localEnglish[0];
        action.hidden = !voice;
        status.textContent = voice ? '' : 'Локальная озвучка недоступна. Прочитайте реплику продавца.';
    }
    synth.addEventListener('voiceschanged', updateVoice);
    updateVoice();
    action.addEventListener('click', () => {
        if (!voice) return;
        synth.cancel();
        const utterance = new SpeechSynthesisUtterance(line.textContent.trim());
        utterance.voice = voice;
        utterance.lang = voice.lang;
        utterance.rate = 0.9;
        utterance.onstart = () => { status.textContent = ''; };
        utterance.onerror = () => { status.textContent = 'Озвучить реплику не удалось. Она доступна текстом.'; };
        synth.speak(utterance);
    });
    window.addEventListener('pagehide', () => synth.cancel());
})();

(() => {
    const action = document.getElementById('share-scene');
    const link = document.getElementById('scene-link');
    const status = document.getElementById('share-status');
    if (!action || !link || !status) return;

    action.hidden = false;
    action.addEventListener('click', async () => {
        status.textContent = '';
        if (navigator.share) {
            try {
                await navigator.share({url: link.value});
                return;
            } catch (error) {
                if (error.name !== 'AbortError' && navigator.clipboard) {
                    try {
                        await navigator.clipboard.writeText(link.value);
                        status.textContent = 'Ссылка скопирована.';
                        return;
                    } catch {
                        // The plain link remains available below.
                    }
                }
            }
        } else if (navigator.clipboard) {
            try {
                await navigator.clipboard.writeText(link.value);
                status.textContent = 'Ссылка скопирована.';
                return;
            } catch {
                // The plain link remains available below.
            }
        }
        link.focus();
        link.select();
        status.textContent = 'Скопируйте гостевую ссылку из поля.';
    });
})();
