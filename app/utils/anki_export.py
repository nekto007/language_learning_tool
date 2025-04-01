import genanki
import random
import hashlib


def create_anki_package(words, output_file, deck_name, card_format, include_pronunciation=False,
                        include_examples=False):
    # Generate a consistent model ID based on the card format and options
    model_seed = f"{card_format}_{include_pronunciation}_{include_examples}"
    model_id = int(hashlib.md5(model_seed.encode('utf-8')).hexdigest()[:8], 16)

    # Create model based on card format
    if card_format == 'basic':
        model = genanki.Model(
            model_id,
            'Basic English-Russian',
            fields=[
                {'name': 'English'},
                {'name': 'Russian'},
                {'name': 'Pronunciation'},
                {'name': 'Examples'}
            ],
            templates=[{
                'name': 'English to Russian',
                'qfmt': '{{English}}{{#Pronunciation}}<br>{{Pronunciation}}{{/Pronunciation}}',
                'afmt': '{{FrontSide}}<hr id="answer">{{Russian}}{{#Examples}}<br><br>{{Examples}}{{/Examples}}'
            }]
        )
    elif card_format == 'reversed':
        model = genanki.Model(
            model_id,
            'Reversed English-Russian',
            fields=[
                {'name': 'English'},
                {'name': 'Russian'},
                {'name': 'Pronunciation'},
                {'name': 'Examples'}
            ],
            templates=[
                {
                    'name': 'English to Russian',
                    'qfmt': '{{English}}{{#Pronunciation}}<br>{{Pronunciation}}{{/Pronunciation}}',
                    'afmt': '{{FrontSide}}<hr id="answer">{{Russian}}{{#Examples}}<br><br>{{Examples}}{{/Examples}}'
                },
                {
                    'name': 'Russian to English',
                    'qfmt': '{{Russian}}',
                    'afmt': '{{FrontSide}}<hr id="answer">{{English}}{{#Pronunciation}}<br>{{Pronunciation}}{{/Pronunciation}}{{#Examples}}<br><br>{{Examples}}{{/Examples}}'
                }
            ]
        )
    elif card_format == 'cloze':
        model = genanki.Model(
            model_id,
            'Cloze English-Russian',
            fields=[
                {'name': 'Text'},
                {'name': 'Extra'},
                {'name': 'Pronunciation'}
            ],
            templates=[{
                'name': 'Cloze',
                'qfmt': '{{cloze:Text}}{{#Pronunciation}}<br>{{Pronunciation}}{{/Pronunciation}}',
                'afmt': '{{cloze:Text}}<hr id="answer">{{Extra}}{{#Pronunciation}}<br>{{Pronunciation}}{{/Pronunciation}}'
            }],
            model_type=genanki.Model.CLOZE
        )
    else:
        raise ValueError(f"Unsupported card format: {card_format}")

    # Generate a consistent deck ID based on the deck name
    deck_id = int(hashlib.md5(deck_name.encode('utf-8')).hexdigest()[:8], 16)
    deck = genanki.Deck(deck_id, deck_name)

    # Create media files collection
    media_files = []

    # Add notes for each word
    for word in words:
        if card_format in ['basic', 'reversed']:
            # Parse and format examples if needed
            examples = ''
            if include_examples and word.sentences:
                examples = word.sentences.replace('<br>', '\n')

            # Pronunciation field
            pronunciation = ''
            if include_pronunciation and word.listening:
                pronunciation = word.listening

                # Extract audio filename from [sound:filename] format
                if '[sound:' in pronunciation and ']' in pronunciation:
                    audio_file = pronunciation[7:-1]  # Remove [sound: and ]
                    from flask import current_app
                    audio_path = os.path.join(current_app.config['AUDIO_UPLOAD_FOLDER'], audio_file)
                    if os.path.exists(audio_path):
                        media_files.append(audio_path)

            note = genanki.Note(
                model=model,
                fields=[
                    word.english_word,
                    word.russian_word or '',
                    pronunciation,
                    examples
                ]
            )
            deck.add_note(note)

        elif card_format == 'cloze':
            # For cloze, create a cloze deletion from the example sentence
            text = ''
            if word.sentences:
                sentences = word.sentences.split('<br>')
                if len(sentences) >= 2:
                    eng_sentence = sentences[0]
                    rus_sentence = sentences[1]

                    # Create cloze by replacing the word with {{c1::word}}
                    cloze_text = eng_sentence.replace(
                        word.english_word,
                        f"{{{{c1::{word.english_word}}}}}"
                    )
                    text = cloze_text
                    extra = f"{word.russian_word}\n\n{rus_sentence}"
                else:
                    text = f"{{{{c1::{word.english_word}}}}} - Learn this word"
                    extra = word.russian_word
            else:
                text = f"{{{{c1::{word.english_word}}}}} - Learn this word"
                extra = word.russian_word

            # Pronunciation field
            pronunciation = ''
            if include_pronunciation and word.listening:
                pronunciation = word.listening

                # Extract audio filename from [sound:filename] format
                if '[sound:' in pronunciation and ']' in pronunciation:
                    audio_file = pronunciation[7:-1]  # Remove [sound: and ]
                    from flask import current_app
                    audio_path = os.path.join(current_app.config['AUDIO_UPLOAD_FOLDER'], audio_file)
                    if os.path.exists(audio_path):
                        media_files.append(audio_path)

            note = genanki.Note(
                model=model,
                fields=[text, extra, pronunciation]
            )
            deck.add_note(note)

    # Create package
    package = genanki.Package(deck)

    # Add media files if any
    if media_files:
        package.media_files = media_files

    # Write to file
    package.write_to_file(output_file)

    return output_file
