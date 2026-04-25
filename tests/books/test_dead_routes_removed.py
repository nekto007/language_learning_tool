"""Verify legacy reader-v2 endpoint and grammar_public blueprint are gone."""
import pytest


class TestLegacyReaderV2Removed:
    @pytest.mark.smoke
    def test_no_reader_v2_endpoint(self, app):
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        assert not any('reader-v2' in r or '/v2' in r for r in rules), (
            f"reader-v2 routes should be removed; found: "
            f"{[r for r in rules if 'reader-v2' in r or '/v2' in r]}"
        )

    @pytest.mark.smoke
    def test_no_read_book_v2_view(self, app):
        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
        assert 'books.read_book_v2' not in endpoints


class TestGrammarPublicRemoved:
    @pytest.mark.smoke
    def test_no_grammar_public_blueprint(self, app):
        endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
        assert not any(e.startswith('grammar_public.') for e in endpoints)

    def test_grammar_public_module_absent(self):
        with pytest.raises(ImportError):
            __import__('app.grammar_public')
