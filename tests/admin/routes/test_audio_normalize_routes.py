# tests/admin/routes/test_audio_normalize_routes.py

"""Tests for audio normalize/fill/fix-all endpoints (Task 29 coverage gap)."""

import pytest
from unittest.mock import patch


class TestNormalizeListeningFields:
    """Tests for normalize_listening_fields endpoint."""

    @pytest.mark.smoke
    @patch("app.admin.routes.audio_routes.AudioManagementService.normalize_listening_fields")
    def test_success(self, mock_normalize, admin_client, mock_admin_user):
        mock_normalize.return_value = (True, 5, "Normalized 5 fields")

        resp = admin_client.post("/admin/audio/normalize-listening-fields")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["fixed_count"] == 5

    @patch("app.admin.routes.audio_routes.AudioManagementService.normalize_listening_fields")
    def test_error_returns_500(self, mock_normalize, admin_client, mock_admin_user):
        mock_normalize.side_effect = Exception("DB error")

        resp = admin_client.post("/admin/audio/normalize-listening-fields")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["success"] is False

    def test_requires_admin(self, client):
        resp = client.post("/admin/audio/normalize-listening-fields")
        assert resp.status_code == 302


class TestFillEmptyListeningFields:
    """Tests for fill_empty_listening_fields endpoint."""

    @pytest.mark.smoke
    @patch("app.admin.routes.audio_routes.AudioManagementService.fill_empty_listening_fields")
    def test_success(self, mock_fill, admin_client, mock_admin_user):
        mock_fill.return_value = (True, 3, "Filled 3 fields")

        resp = admin_client.post("/admin/audio/fill-empty-listening")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["fixed_count"] == 3

    @patch("app.admin.routes.audio_routes.AudioManagementService.fill_empty_listening_fields")
    def test_error_returns_500(self, mock_fill, admin_client, mock_admin_user):
        mock_fill.side_effect = Exception("error")

        resp = admin_client.post("/admin/audio/fill-empty-listening")
        assert resp.status_code == 500

    def test_requires_admin(self, client):
        resp = client.post("/admin/audio/fill-empty-listening")
        assert resp.status_code == 302


class TestFixAllAudio:
    """Tests for fix_all_audio combined endpoint."""

    @pytest.mark.smoke
    @patch("app.admin.routes.audio_routes.AudioManagementService.fill_empty_listening_fields")
    @patch("app.admin.routes.audio_routes.AudioManagementService.normalize_listening_fields")
    @patch("app.admin.routes.audio_routes.AudioManagementService.fix_listening_fields")
    @patch("app.admin.routes.audio_routes.AudioManagementService.update_download_status")
    def test_success_returns_results_list(
        self, mock_update, mock_fix, mock_normalize, mock_fill,
        admin_client, mock_admin_user,
    ):
        mock_update.return_value = 10
        mock_fix.return_value = (True, 2, "Fixed 2")
        mock_normalize.return_value = (True, 5, "Normalized 5")
        mock_fill.return_value = (True, 3, "Filled 3")

        resp = admin_client.post("/admin/audio/fix-all")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "results" in data
        assert len(data["results"]) >= 1

    def test_requires_admin(self, client):
        resp = client.post("/admin/audio/fix-all")
        assert resp.status_code == 302


class TestImportPhrasalVerbsGet:
    """Tests for import_phrasal_verbs GET route."""

    @pytest.mark.smoke
    @patch("app.admin.routes.word_routes.WordManagementService.get_phrasal_verb_statistics")
    def test_get_renders_form(self, mock_stats, admin_client, mock_admin_user):
        mock_stats.return_value = {"total": 100, "with_audio": 80}

        resp = admin_client.get("/admin/words/import-phrasal-verbs")
        assert resp.status_code == 200

    def test_requires_admin(self, client):
        resp = client.get("/admin/words/import-phrasal-verbs")
        assert resp.status_code == 302
