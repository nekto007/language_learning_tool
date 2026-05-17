/**
 * SpeechAPI — thin wrapper around Web Speech Recognition API.
 * Handles unsupported browsers gracefully; language fixed to en-US.
 */
class SpeechAPI {
    constructor() {
        this._recognition = null;
    }

    isSupported() {
        return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    }

    startRecognition(onResult, onError) {
        if (!this.isSupported()) {
            onError(new Error('SpeechRecognition not supported in this browser'));
            return;
        }

        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        this._recognition = new Recognition();
        this._recognition.lang = 'en-US';
        this._recognition.continuous = false;
        this._recognition.interimResults = false;

        this._recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            onResult(transcript);
        };

        this._recognition.onerror = (event) => {
            onError(new Error(event.error || 'Speech recognition error'));
        };

        this._recognition.start();
    }

    stopRecognition() {
        if (this._recognition) {
            this._recognition.stop();
            this._recognition = null;
        }
    }
}

export default SpeechAPI;
