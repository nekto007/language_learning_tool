"""
Tests for NLP setup module
Тесты модуля настройки NLP
"""
import pytest
import ssl
from unittest.mock import patch, MagicMock, call
from app.nlp.setup import (
    setup_ssl_context,
    download_nltk_resources,
    get_english_vocabulary,
    get_brown_words,
    get_stopwords,
    initialize_nltk,
    REQUIRED_RESOURCES
)


class TestSetupSslContext:
    """Тесты функции setup_ssl_context"""

    @patch('app.nlp.setup.ssl')
    def test_setup_ssl_context_success(self, mock_ssl):
        """Тест успешной настройки SSL контекста"""
        mock_ssl._create_unverified_context = MagicMock()

        setup_ssl_context()

        # Verify SSL context was modified
        assert mock_ssl._create_default_https_context == mock_ssl._create_unverified_context

    @patch('app.nlp.setup.ssl')
    @patch('app.nlp.setup.logger')
    def test_setup_ssl_context_attribute_error(self, mock_logger, mock_ssl):
        """Тест обработки ошибки AttributeError"""
        # Simulate AttributeError when accessing _create_unverified_context
        del mock_ssl._create_unverified_context

        setup_ssl_context()

        # Should log warning when AttributeError occurs
        mock_logger.warning.assert_called_with("Could not modify SSL context")


class TestDownloadNltkResources:
    """Тесты функции download_nltk_resources"""

    @patch('app.nlp.setup.setup_ssl_context')
    @patch('app.nlp.setup.nltk.data.find')
    @patch('app.nlp.setup.nltk.download')
    @patch('app.nlp.setup.logger')
    def test_download_already_exists(self, mock_logger, mock_download, mock_find, mock_ssl):
        """Тест когда ресурсы уже загружены"""
        # Simulate all resources already exist
        mock_find.return_value = True

        download_nltk_resources()

        # Should check for each resource
        assert mock_find.call_count == len(REQUIRED_RESOURCES)
        # Should not download anything
        assert not mock_download.called

    @patch('app.nlp.setup.setup_ssl_context')
    @patch('app.nlp.setup.nltk.data.find')
    @patch('app.nlp.setup.nltk.download')
    @patch('app.nlp.setup.logger')
    def test_download_missing_resources(self, mock_logger, mock_download, mock_find, mock_ssl):
        """Тест загрузки отсутствующих ресурсов"""
        # Simulate resources not found
        mock_find.side_effect = LookupError()

        download_nltk_resources()

        # Should attempt to download all resources
        assert mock_download.call_count == len(REQUIRED_RESOURCES)
        # Verify download was called with quiet=True
        for call_args in mock_download.call_args_list:
            assert call_args[1].get('quiet') == True

    @patch('app.nlp.setup.setup_ssl_context')
    @patch('app.nlp.setup.nltk.data.find')
    @patch('app.nlp.setup.nltk.download')
    @patch('app.nlp.setup.logger')
    def test_download_handles_exceptions(self, mock_logger, mock_download, mock_find, mock_ssl):
        """Тест обработки ошибок при загрузке"""
        # Simulate download failing
        mock_find.side_effect = LookupError()
        mock_download.side_effect = Exception("Network error")

        # Should not raise exception
        download_nltk_resources()

        # Should log errors for all resources
        assert mock_logger.error.call_count == len(REQUIRED_RESOURCES)

    @patch('app.nlp.setup.setup_ssl_context')
    @patch('app.nlp.setup.nltk.data.find')
    @patch('app.nlp.setup.logger')
    def test_download_checks_correct_paths(self, mock_logger, mock_find, mock_ssl):
        """Тест что проверяются правильные пути ресурсов"""
        mock_find.return_value = True

        download_nltk_resources()

        # Verify find was called with correct paths
        expected_calls = [call(f"tokenizers/{resource}") for resource in REQUIRED_RESOURCES]
        mock_find.assert_has_calls(expected_calls, any_order=True)


class TestGetEnglishVocabulary:
    """Тесты функции get_english_vocabulary"""

    @patch('app.nlp.setup.nltk_words.words')
    def test_get_english_vocabulary_returns_set(self, mock_words):
        """Тест что функция возвращает множество"""
        mock_words.return_value = ['Hello', 'World', 'Test']

        result = get_english_vocabulary()

        assert isinstance(result, set)
        assert len(result) == 3

    @patch('app.nlp.setup.nltk_words.words')
    def test_get_english_vocabulary_lowercase(self, mock_words):
        """Тест что слова преобразуются в нижний регистр"""
        mock_words.return_value = ['Hello', 'WORLD', 'TeSt']

        result = get_english_vocabulary()

        assert 'hello' in result
        assert 'world' in result
        assert 'test' in result
        assert 'Hello' not in result
        assert 'WORLD' not in result

    @patch('app.nlp.setup.nltk_words.words')
    def test_get_english_vocabulary_empty(self, mock_words):
        """Тест с пустым списком слов"""
        mock_words.return_value = []

        result = get_english_vocabulary()

        assert isinstance(result, set)
        assert len(result) == 0

    @patch('app.nlp.setup.nltk_words.words')
    def test_get_english_vocabulary_duplicates_removed(self, mock_words):
        """Тест что дубликаты удаляются"""
        mock_words.return_value = ['test', 'Test', 'TEST']

        result = get_english_vocabulary()

        # All should become 'test', resulting in 1 unique word
        assert len(result) == 1
        assert 'test' in result


class TestGetBrownWords:
    """Тесты функции get_brown_words"""

    @patch('app.nlp.setup.brown.words')
    def test_get_brown_words_returns_set(self, mock_words):
        """Тест что функция возвращает множество"""
        mock_words.return_value = ['the', 'quick', 'brown', 'fox']

        result = get_brown_words()

        assert isinstance(result, set)
        assert len(result) == 4

    @patch('app.nlp.setup.brown.words')
    def test_get_brown_words_content(self, mock_words):
        """Тест содержимого Brown corpus"""
        test_words = ['word1', 'word2', 'word3']
        mock_words.return_value = test_words

        result = get_brown_words()

        assert result == set(test_words)

    @patch('app.nlp.setup.brown.words')
    def test_get_brown_words_empty(self, mock_words):
        """Тест с пустым Brown corpus"""
        mock_words.return_value = []

        result = get_brown_words()

        assert isinstance(result, set)
        assert len(result) == 0


class TestGetStopwords:
    """Тесты функции get_stopwords"""

    @patch('app.nlp.setup.stopwords.words')
    def test_get_stopwords_returns_set(self, mock_words):
        """Тест что функция возвращает множество"""
        mock_words.return_value = ['the', 'a', 'an', 'and']

        result = get_stopwords()

        assert isinstance(result, set)
        assert len(result) == 4

    @patch('app.nlp.setup.stopwords.words')
    def test_get_stopwords_calls_with_english(self, mock_words):
        """Тест что запрашиваются английские стоп-слова"""
        mock_words.return_value = ['the', 'a']

        get_stopwords()

        mock_words.assert_called_once_with('english')

    @patch('app.nlp.setup.stopwords.words')
    def test_get_stopwords_content(self, mock_words):
        """Тест содержимого стоп-слов"""
        test_stopwords = ['i', 'me', 'my', 'the']
        mock_words.return_value = test_stopwords

        result = get_stopwords()

        assert result == set(test_stopwords)


class TestInitializeNltk:
    """Тесты функции initialize_nltk"""

    @patch('app.nlp.setup.get_stopwords')
    @patch('app.nlp.setup.get_brown_words')
    @patch('app.nlp.setup.get_english_vocabulary')
    def test_initialize_nltk_returns_tuple(self, mock_vocab, mock_brown, mock_stop):
        """Тест что функция возвращает кортеж из 3 элементов"""
        mock_vocab.return_value = {'word1'}
        mock_brown.return_value = {'brown1'}
        mock_stop.return_value = {'the'}

        result = initialize_nltk()

        assert isinstance(result, tuple)
        assert len(result) == 3

    @patch('app.nlp.setup.get_stopwords')
    @patch('app.nlp.setup.get_brown_words')
    @patch('app.nlp.setup.get_english_vocabulary')
    def test_initialize_nltk_calls_all_functions(self, mock_vocab, mock_brown, mock_stop):
        """Тест что вызываются все вспомогательные функции"""
        mock_vocab.return_value = set()
        mock_brown.return_value = set()
        mock_stop.return_value = set()

        initialize_nltk()

        mock_vocab.assert_called_once()
        mock_brown.assert_called_once()
        mock_stop.assert_called_once()

    @patch('app.nlp.setup.get_stopwords')
    @patch('app.nlp.setup.get_brown_words')
    @patch('app.nlp.setup.get_english_vocabulary')
    def test_initialize_nltk_returns_correct_order(self, mock_vocab, mock_brown, mock_stop):
        """Тест правильного порядка возвращаемых значений"""
        vocab_set = {'vocab'}
        brown_set = {'brown'}
        stop_set = {'stop'}

        mock_vocab.return_value = vocab_set
        mock_brown.return_value = brown_set
        mock_stop.return_value = stop_set

        english_vocab, brown_words, stop_words = initialize_nltk()

        assert english_vocab == vocab_set
        assert brown_words == brown_set
        assert stop_words == stop_set

    @patch('app.nlp.setup.get_stopwords')
    @patch('app.nlp.setup.get_brown_words')
    @patch('app.nlp.setup.get_english_vocabulary')
    def test_initialize_nltk_with_real_data(self, mock_vocab, mock_brown, mock_stop):
        """Тест инициализации с реалистичными данными"""
        mock_vocab.return_value = {'hello', 'world', 'test'}
        mock_brown.return_value = {'the', 'quick', 'brown'}
        mock_stop.return_value = {'a', 'an', 'the'}

        english_vocab, brown_words, stop_words = initialize_nltk()

        assert len(english_vocab) == 3
        assert len(brown_words) == 3
        assert len(stop_words) == 3


class TestRequiredResources:
    """Тесты константы REQUIRED_RESOURCES"""

    def test_required_resources_is_list(self):
        """Тест что REQUIRED_RESOURCES это список"""
        assert isinstance(REQUIRED_RESOURCES, list)

    def test_required_resources_not_empty(self):
        """Тест что список ресурсов не пустой"""
        assert len(REQUIRED_RESOURCES) > 0

    def test_required_resources_contains_expected_items(self):
        """Тест что список содержит ожидаемые ресурсы"""
        expected_resources = ['punkt', 'stopwords', 'wordnet', 'words', 'brown']

        for resource in expected_resources:
            assert resource in REQUIRED_RESOURCES

    def test_required_resources_all_strings(self):
        """Тест что все ресурсы это строки"""
        for resource in REQUIRED_RESOURCES:
            assert isinstance(resource, str)

    def test_required_resources_no_duplicates(self):
        """Тест что нет дубликатов"""
        assert len(REQUIRED_RESOURCES) == len(set(REQUIRED_RESOURCES))
