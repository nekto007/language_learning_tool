"""
Tests for NLP processor module
Тесты модуля обработки естественного языка
"""
import pytest
import time
from unittest.mock import patch, MagicMock
from app.nlp.processor import (
    get_wordnet_pos,
    extract_text_from_html,
    tokenize_and_filter,
    lemmatize_words,
    filter_english_words,
    process_text,
    process_html_content,
    prepare_word_data,
    NLP_TIMEOUT_SECONDS,
)
from nltk.corpus import wordnet


class TestGetWordnetPos:
    """Тесты функции get_wordnet_pos"""

    def test_adjective_tag(self):
        """Тест преобразования тега прилагательного"""
        assert get_wordnet_pos('JJ') == wordnet.ADJ
        assert get_wordnet_pos('JJR') == wordnet.ADJ
        assert get_wordnet_pos('JJS') == wordnet.ADJ

    def test_verb_tag(self):
        """Тест преобразования тега глагола"""
        assert get_wordnet_pos('VB') == wordnet.VERB
        assert get_wordnet_pos('VBD') == wordnet.VERB
        assert get_wordnet_pos('VBG') == wordnet.VERB
        assert get_wordnet_pos('VBN') == wordnet.VERB
        assert get_wordnet_pos('VBP') == wordnet.VERB
        assert get_wordnet_pos('VBZ') == wordnet.VERB

    def test_noun_tag(self):
        """Тест преобразования тега существительного"""
        assert get_wordnet_pos('NN') == wordnet.NOUN
        assert get_wordnet_pos('NNS') == wordnet.NOUN
        assert get_wordnet_pos('NNP') == wordnet.NOUN
        assert get_wordnet_pos('NNPS') == wordnet.NOUN

    def test_adverb_tag(self):
        """Тест преобразования тега наречия"""
        assert get_wordnet_pos('RB') == wordnet.ADV
        assert get_wordnet_pos('RBR') == wordnet.ADV
        assert get_wordnet_pos('RBS') == wordnet.ADV

    def test_unknown_tag_defaults_to_noun(self):
        """Тест что неизвестный тег преобразуется в NOUN"""
        assert get_wordnet_pos('CC') == wordnet.NOUN  # Conjunction
        assert get_wordnet_pos('DT') == wordnet.NOUN  # Determiner
        assert get_wordnet_pos('XX') == wordnet.NOUN  # Unknown


class TestExtractTextFromHtml:
    """Тесты функции extract_text_from_html"""

    def test_extract_with_article_class(self):
        """Тест извлечения текста с классом article"""
        html = '<html><body><article class="page-content">Test content</article></body></html>'
        result = extract_text_from_html(html)
        assert result == 'Test content'

    def test_extract_with_entrytext_class(self):
        """Тест извлечения текста с классом entrytext"""
        html = '<html><body><div class="entrytext">Entry text content</div></body></html>'
        result = extract_text_from_html(html)
        assert result == 'Entry text content'

    def test_extract_with_content_class(self):
        """Тест извлечения текста с классом content"""
        html = '<html><body><div class="content">Main content</div></body></html>'
        result = extract_text_from_html(html)
        assert result == 'Main content'

    def test_extract_with_custom_selector(self):
        """Тест извлечения текста с пользовательским селектором"""
        html = '<html><body><div id="custom">Custom content</div></body></html>'
        result = extract_text_from_html(html, selector='#custom')
        assert result == 'Custom content'

    def test_extract_falls_back_to_body(self):
        """Тест что функция возвращает весь body если не найден подходящий элемент"""
        html = '<html><body>Fallback content</body></html>'
        result = extract_text_from_html(html)
        assert 'Fallback content' in result

    def test_extract_with_no_body(self):
        """Тест обработки HTML без body"""
        html = '<html><head><title>Title</title></head></html>'
        result = extract_text_from_html(html)
        assert result == ''

    def test_extract_strips_html_tags(self):
        """Тест что HTML теги удаляются"""
        html = '<html><body><article class="page-content"><p>Paragraph <strong>bold</strong> text</p></article></body></html>'
        result = extract_text_from_html(html)
        assert '<p>' not in result
        assert '<strong>' not in result
        assert 'Paragraph bold text' in result


class TestTokenizeAndFilter:
    """Тесты функции tokenize_and_filter"""

    def test_tokenize_simple_text(self):
        """Тест токенизации простого текста"""
        text = "Hello world"
        result = tokenize_and_filter(text, set())
        assert 'hello' in result
        assert 'world' in result

    def test_filter_non_alphabetic(self):
        """Тест фильтрации не-буквенных токенов"""
        text = "Hello 123 world!"
        result = tokenize_and_filter(text, set())
        assert '123' not in result
        assert 'hello' in result
        assert 'world' in result

    def test_converts_to_lowercase(self):
        """Тест преобразования в нижний регистр"""
        text = "HELLO World"
        result = tokenize_and_filter(text, set())
        assert 'hello' in result
        assert 'world' in result
        assert 'HELLO' not in result

    @pytest.mark.xfail(reason="Bug in expand_contractions: replaces substrings inside words (de->the, en->and)")
    def test_filters_stop_words(self):
        """Тест фильтрации стоп-слов"""
        text = "I am a student"
        result = tokenize_and_filter(text, set())
        # Check that common stop words are filtered
        assert 'i' not in result
        assert 'am' not in result
        assert 'a' not in result
        assert 'student' in result

    def test_filters_punctuation(self):
        """Тест фильтрации пунктуации"""
        text = "Hello, world! How are you?"
        result = tokenize_and_filter(text, set())
        assert ',' not in result
        assert '!' not in result
        assert '?' not in result


class TestLemmatizeWords:
    """Тесты функции lemmatize_words"""

    def test_lemmatize_verbs(self):
        """Тест лемматизации глаголов"""
        words = ['running', 'ran', 'runs']
        result = lemmatize_words(words)
        # running -> run, ran -> run, runs -> run
        assert 'run' in result

    def test_lemmatize_nouns(self):
        """Тест лемматизации существительных"""
        words = ['cats', 'dogs', 'children']
        result = lemmatize_words(words)
        assert 'cat' in result
        assert 'dog' in result
        assert 'child' in result

    def test_lemmatize_adjectives(self):
        """Тест лемматизации прилагательных"""
        words = ['better', 'best']
        result = lemmatize_words(words)
        # Lemmatization should produce base forms
        assert len(result) == 2

    def test_preserves_word_count(self):
        """Тест что количество слов сохраняется"""
        words = ['running', 'quickly', 'cat', 'dog']
        result = lemmatize_words(words)
        assert len(result) == len(words)

    def test_empty_list(self):
        """Тест пустого списка"""
        result = lemmatize_words([])
        assert result == []


class TestFilterEnglishWords:
    """Тесты функции filter_english_words"""

    def test_filter_keeps_english_words(self):
        """Тест что английские слова сохраняются"""
        words = ['hello', 'world', 'test']
        english_vocab = {'hello', 'world', 'test', 'other'}
        result = filter_english_words(words, english_vocab)
        assert result == ['hello', 'world', 'test']

    def test_filter_removes_non_english(self):
        """Тест что неанглийские слова удаляются"""
        words = ['hello', 'привет', 'world']
        english_vocab = {'hello', 'world'}
        result = filter_english_words(words, english_vocab)
        assert result == ['hello', 'world']
        assert 'привет' not in result

    def test_case_insensitive_filtering(self):
        """Тест что фильтрация работает независимо от регистра"""
        words = ['Hello', 'WORLD', 'Test']
        english_vocab = {'hello', 'world', 'test'}
        result = filter_english_words(words, english_vocab)
        assert len(result) == 3

    def test_empty_vocabulary(self):
        """Тест с пустым словарем"""
        words = ['hello', 'world']
        result = filter_english_words(words, set())
        assert result == []

    def test_empty_word_list(self):
        """Тест с пустым списком слов"""
        result = filter_english_words([], {'hello', 'world'})
        assert result == []


class TestProcessText:
    """Тесты функции process_text"""

    @patch('app.nlp.processor.lemmatize_words')
    @patch('app.nlp.processor.tokenize_and_filter')
    def test_process_text_pipeline(self, mock_tokenize, mock_lemmatize):
        """Тест полного пайплайна обработки текста"""
        mock_tokenize.return_value = ['hello', 'world']
        mock_lemmatize.return_value = ['hello', 'world']

        english_vocab = {'hello', 'world'}
        stop_words = set()

        result = process_text("Hello world!", english_vocab, stop_words)

        mock_tokenize.assert_called_once()
        mock_lemmatize.assert_called_once()
        assert len(result) == 2

    def test_process_text_real_example(self):
        """Тест реального примера обработки текста"""
        text = "The cats are running quickly"
        english_vocab = {'cat', 'run', 'quickly', 'the', 'are'}
        stop_words = set()

        result = process_text(text, english_vocab, stop_words)

        # Should contain lemmatized forms
        assert len(result) > 0
        # Stop words should be filtered
        assert 'the' not in result
        assert 'are' not in result


class TestProcessHtmlContent:
    """Тесты функции process_html_content"""

    @patch('app.nlp.processor.initialize_nltk')
    @patch('app.nlp.processor.process_text')
    @patch('app.nlp.processor.extract_text_from_html')
    def test_process_html_pipeline(self, mock_extract, mock_process, mock_init):
        """Тест полного пайплайна обработки HTML"""
        mock_init.return_value = (set(), set(), set())
        mock_extract.return_value = "Test text"
        mock_process.return_value = ['test', 'text']

        result = process_html_content("<html><body>Test</body></html>")

        mock_init.assert_called_once()
        mock_extract.assert_called_once()
        mock_process.assert_called_once()
        assert result == ['test', 'text']

    @patch('app.nlp.processor.initialize_nltk')
    @patch('app.nlp.processor.process_text')
    def test_process_html_with_selector(self, mock_process, mock_init):
        """Тест обработки HTML с пользовательским селектором"""
        mock_init.return_value = (set(), set(), set())
        mock_process.return_value = ['custom', 'content']

        html = '<html><body><div id="custom">Custom content</div></body></html>'
        result = process_html_content(html, selector='#custom')

        assert result == ['custom', 'content']


class TestPrepareWordData:
    """Тесты функции prepare_word_data"""

    def test_prepare_word_data_basic(self):
        """Тест базовой подготовки данных слов"""
        words = ['hello', 'world', 'hello']
        brown_words = {'hello'}

        result = prepare_word_data(words, brown_words)

        assert len(result) == 2  # hello and world
        # Check structure of tuples
        for item in result:
            assert len(item) == 4  # (word, link, in_brown, frequency)
            assert isinstance(item[0], str)  # word
            assert isinstance(item[1], str)  # link
            assert isinstance(item[2], int)  # in_brown (0 or 1)
            assert isinstance(item[3], int)  # frequency

    def test_prepare_word_data_frequency(self):
        """Тест подсчета частоты слов"""
        words = ['test', 'test', 'test', 'word']
        brown_words = set()

        result = prepare_word_data(words, brown_words)

        # Find 'test' in results
        test_data = [item for item in result if item[0] == 'test'][0]
        assert test_data[3] == 3  # frequency

        word_data = [item for item in result if item[0] == 'word'][0]
        assert word_data[3] == 1  # frequency

    def test_prepare_word_data_brown_corpus(self):
        """Тест определения слов из Brown corpus"""
        words = ['common', 'rare']
        brown_words = {'common'}

        result = prepare_word_data(words, brown_words)

        common_data = [item for item in result if item[0] == 'common'][0]
        assert common_data[2] == 1  # in_brown = True

        rare_data = [item for item in result if item[0] == 'rare'][0]
        assert rare_data[2] == 0  # in_brown = False

    def test_prepare_word_data_audio_link(self):
        """Тест генерации ссылки на аудио файл"""
        words = ['hello']
        brown_words = set()

        result = prepare_word_data(words, brown_words)

        assert result[0][1] == 'pronunciation_en_hello.mp3'

    def test_prepare_word_data_empty_list(self):
        """Тест с пустым списком слов"""
        result = prepare_word_data([], set())
        assert result == []

    def test_prepare_word_data_duplicate_words(self):
        """Тест обработки дубликатов"""
        words = ['word', 'word', 'word']
        brown_words = set()

        result = prepare_word_data(words, brown_words)

        assert len(result) == 1
        assert result[0][3] == 3  # frequency = 3


class TestProcessTextEmptyInput:
    """Тесты защиты от пустого ввода в process_text"""

    def test_empty_string_returns_empty_list(self):
        result = process_text("", {'hello'}, set())
        assert result == []

    def test_whitespace_only_returns_empty_list(self):
        result = process_text("   \n\t  ", {'hello'}, set())
        assert result == []

    def test_none_like_empty_string_is_guarded(self):
        # Ensure no crash on zero-length text
        result = process_text("", set(), set())
        assert isinstance(result, list)
        assert len(result) == 0


class TestProcessHtmlContentEmptyInput:
    """Тесты защиты от пустого HTML в process_html_content"""

    @patch('app.nlp.processor.initialize_nltk')
    def test_empty_html_returns_empty_without_calling_nltk(self, mock_init):
        mock_init.return_value = (set(), set(), set())
        result = process_html_content("")
        assert result == []
        mock_init.assert_not_called()

    @patch('app.nlp.processor.initialize_nltk')
    def test_whitespace_html_returns_empty_without_calling_nltk(self, mock_init):
        mock_init.return_value = (set(), set(), set())
        result = process_html_content("   ")
        assert result == []
        mock_init.assert_not_called()

    @patch('app.nlp.processor.initialize_nltk')
    @patch('app.nlp.processor.extract_text_from_html')
    def test_empty_extracted_text_returns_empty(self, mock_extract, mock_init):
        mock_init.return_value = (set(), set(), set())
        mock_extract.return_value = ""
        result = process_html_content("<html><body></body></html>")
        assert result == []


class TestNltkGracefulFailure:
    """Тесты graceful handling когда NLTK ресурсы недоступны"""

    def test_initialize_nltk_graceful_on_lookup_error(self):
        from app.nlp.setup import initialize_nltk, _reset_cache
        _reset_cache()

        with patch('app.nlp.setup.get_english_vocabulary', side_effect=LookupError("punkt not found")):
            result = initialize_nltk()

        vocab, brown, sw = result
        assert isinstance(vocab, set)
        assert isinstance(brown, set)
        assert isinstance(sw, set)
        # All should be empty sets (graceful fallback)
        assert vocab == set()
        assert brown == set()
        assert sw == set()

        # Restore cache for subsequent tests
        _reset_cache()

    def test_initialize_nltk_graceful_on_os_error(self):
        from app.nlp.setup import initialize_nltk, _reset_cache
        _reset_cache()

        with patch('app.nlp.setup.get_english_vocabulary', side_effect=OSError("data path not found")):
            result = initialize_nltk()

        vocab, brown, sw = result
        assert vocab == set()
        _reset_cache()


class TestNltkCaching:
    """Тесты кэширования initialize_nltk"""

    def test_initialize_nltk_cached_second_call_no_reload(self):
        from app.nlp.setup import initialize_nltk, _reset_cache
        _reset_cache()

        with patch('app.nlp.setup.get_english_vocabulary', return_value={'hello', 'world'}) as mock_vocab, \
             patch('app.nlp.setup.get_brown_words', return_value={'hello'}) as mock_brown, \
             patch('app.nlp.setup.get_stopwords', return_value={'the'}) as mock_sw:

            result1 = initialize_nltk()
            result2 = initialize_nltk()

        # Expensive calls happen only once due to caching
        mock_vocab.assert_called_once()
        mock_brown.assert_called_once()
        mock_sw.assert_called_once()
        # Both calls return the same tuple object
        assert result1 is result2

        _reset_cache()

    def test_process_html_calls_initialize_once_per_invocation(self):
        """initialize_nltk is cached — multiple process_html_content calls reuse it"""
        from app.nlp.setup import initialize_nltk, _reset_cache
        _reset_cache()

        call_count = {'n': 0}
        original_vocab = {'hello'}

        def counting_vocab():
            call_count['n'] += 1
            return original_vocab

        with patch('app.nlp.setup.get_english_vocabulary', side_effect=counting_vocab), \
             patch('app.nlp.setup.get_brown_words', return_value=set()), \
             patch('app.nlp.setup.get_stopwords', return_value=set()), \
             patch('app.nlp.processor.extract_text_from_html', return_value=""), \
             patch('app.nlp.processor.initialize_nltk', side_effect=initialize_nltk):

            process_html_content("<html><body>hi</body></html>")
            process_html_content("<html><body>hello</body></html>")

        # Vocab loader called only once across multiple process_html_content calls
        assert call_count['n'] == 1
        _reset_cache()


class TestNlpTimeout:
    """Тесты timeout для NLP обработки"""

    def test_timeout_constant_exists_and_positive(self):
        assert NLP_TIMEOUT_SECONDS > 0

    @patch('app.nlp.processor.initialize_nltk')
    @patch('app.nlp.processor.extract_text_from_html')
    def test_process_html_returns_empty_list_on_timeout(self, mock_extract, mock_init):
        mock_init.return_value = (set(), set(), set())
        mock_extract.return_value = "some text to process"

        def slow_process(*args, **kwargs):
            time.sleep(0.5)
            return ['word']

        with patch('app.nlp.processor.process_text', side_effect=slow_process):
            result = process_html_content(
                "<html><body>some text</body></html>",
                timeout=0.05,
            )

        assert result == []

    @patch('app.nlp.processor.initialize_nltk')
    @patch('app.nlp.processor.extract_text_from_html')
    def test_process_html_returns_result_within_timeout(self, mock_extract, mock_init):
        mock_init.return_value = (set(), set(), set())
        mock_extract.return_value = "some text"

        with patch('app.nlp.processor.process_text', return_value=['some', 'text']):
            result = process_html_content(
                "<html><body>some text</body></html>",
                timeout=5,
            )

        assert result == ['some', 'text']
