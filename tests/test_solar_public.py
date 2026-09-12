"""Offline regressions: .venv/bin/python -m unittest discover -s tests -v."""

import importlib.util
import io
import os
from contextlib import ExitStack
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from werkzeug.datastructures import FileStorage


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)

    def attributes(self, tag):
        return [attrs for name, attrs in self.tags if name == tag]


class SolarPublicTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        # Block transport and SDK entry points before importing the application.
        # Check call counts too: application exception handlers may swallow errors.
        self.blockers = []
        for target in (
            "socket.socket.connect", "socket.socket.connect_ex",
            "socket.getaddrinfo", "google.auth.default",
            "google.cloud.storage.Client", "googleapiclient.discovery.build",
            "openai.OpenAI",
        ):
            self.blockers.append(stack.enter_context(patch(
                target, side_effect=AssertionError("External access forbidden")
            )))
        stack.enter_context(patch.dict(os.environ, {}, clear=True))
        # Fresh module keeps import-time environment configuration isolated.
        path = Path(__file__).resolve().parents[1] / "main.py"
        spec = importlib.util.spec_from_file_location("main", path)
        self.main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.main)
        self.main.app.config.update(TESTING=True, SECRET_KEY="test-only-secret")
        self.client = self.main.app.test_client()

    def tearDown(self):
        for blocker in self.blockers:
            blocker.assert_not_called()

    def solar_page(self):
        response = self.client.get("/solar")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_solar_event_hook_is_allowlisted_and_pii_free(self):
        event = self.main.track_solar_event(
            "solar_diagnosis_cta_click",
            placement="hero",
        )
        self.assertEqual(
            event["event_name"],
            "solar_diagnosis_cta_click",
        )
        self.assertEqual(event["placement"], "hero")
        self.assertNotIn("name", event)

        self.assertIsNone(
            self.main.track_solar_event(
                "unknown_event",
                placement="hero",
            )
        )
        self.assertIsNone(
            self.main.track_solar_event(
                "solar_diagnosis_cta_click",
                email="customer@example.test",
            )
        )
        self.assertIsNone(
            self.main.track_solar_event(
                "solar_diagnosis_cta_click",
                placement="hero",
                raw_token="secret-token",
            )
        )
        self.assertIsNone(
            self.main.track_solar_event(
                "solar_diagnosis_cta_click",
                placement="x" * 33,
            )
        )

    def test_solar_lp_and_diagnosis_view_events_are_local_only(self):
        with patch.object(self.main, "track_solar_event") as track:
            self.client.get("/solar")
            self.client.get("/solar/diagnosis")

        names = [call.args[0] for call in track.call_args_list]
        self.assertIn("solar_lp_view", names)
        self.assertIn("solar_diagnosis_view", names)

    def test_solar_returns_200_and_diagnosis_ctas(self):
        links = Page(self.solar_page()).attributes("a")
        diagnosis = [a for a in links if a.get("href") == "/solar/diagnosis"]
        self.assertEqual(len(diagnosis), 4)  # header, hero, final, sticky
        self.assertEqual(
            [a.get("data-solar-placement") for a in diagnosis],
            ["header", "hero", "final", "sticky"],
        )
        self.assertTrue(all(
            a.get("data-solar-event") == "solar_diagnosis_cta_click"
            for a in diagnosis
        ))

    def test_diagnosis_displays_application_form_and_csrf(self):
        response = self.client.get("/solar/diagnosis")
        self.assertEqual(response.status_code, 200)
        page = Page(response.get_data(as_text=True))
        self.assertIn("契約前に無料チェック", "".join(page.text))
        form, = page.attributes("form")
        self.assertEqual(form.get("method"), "post")
        self.assertEqual(form.get("enctype"), "multipart/form-data")
        inputs = {a.get("name"): a for a in page.attributes("input")}
        self.assertEqual(inputs["estimate_file"]["type"], "file")
        self.assertIn("privacy_consent", inputs)
        self.assertEqual(inputs["csrf_token"]["type"], "hidden")
        with self.client.session_transaction() as session:
            self.assertTrue(session.get("csrf_token"))
            self.assertEqual(inputs["csrf_token"]["value"], session["csrf_token"])

    def test_diagnosis_ux_dom_contract(self):
        page = Page(self.client.get("/solar/diagnosis").get_data(as_text=True))
        inputs = {a.get("name"): a for a in page.attributes("input")}
        controls = {
            **inputs,
            **{a.get("name"): a for a in page.attributes("textarea")},
        }
        labels = page.attributes("label")
        label_for = {a.get("for") for a in labels if a.get("for")}

        self.assertIn("estimate_file", inputs)
        self.assertIn("privacy_consent", inputs)
        for name in ("municipality", "consultation", "name", "privacy_consent"):
            self.assertIn("required", controls[name])
        for name in ("estimate_file", "postal_code", "municipality", "estimate_amount", "consultation", "name", "phone", "email", "privacy_consent"):
            self.assertIn(name, label_for)

        self.assertEqual(inputs["phone"].get("type"), "tel")
        self.assertEqual(inputs["phone"].get("autocomplete"), "tel")
        self.assertEqual(inputs["phone"].get("inputmode"), "tel")
        self.assertEqual(inputs["email"].get("type"), "email")
        self.assertEqual(inputs["email"].get("autocomplete"), "email")
        self.assertEqual(inputs["email"].get("inputmode"), "email")
        self.assertEqual(inputs["estimate_file"].get("accept"), ".pdf,.jpg,.jpeg,.png")
        html = self.client.get("/solar/diagnosis").get_data(as_text=True)
        self.assertIn("role=\"alert\"", self.main.SOLAR_DIAGNOSIS_HTML)
        self.assertIn("estimate-file-help", html)
        self.assertIn("privacy-consent-help", html)
        self.assertIn("約3分で申込み", html)

    def test_diagnosis_validation_preserves_values_and_marks_field(self):
        self.client.get("/solar/diagnosis")
        with self.client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        response = self.client.post(
            "/solar/diagnosis",
            data={
                "csrf_token": csrf_token,
                "municipality": "",
                "consultation": "金額を確認したい",
                "name": "テスト利用者",
                "email": "test@example.test",
                "privacy_consent": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("市区町村を入力してください。", html)
        self.assertIn('id="municipality-error"', html)
        self.assertIn('aria-invalid="true"', html)
        self.assertIn('value="テスト利用者"', html)
        self.assertIn('value="test@example.test"', html)
        self.assertNotIn("SOLAR DIAGNOSIS ERROR", html)

    def test_diagnosis_rejects_invalid_contact_before_external_write(self):
        self.client.get("/solar/diagnosis")
        with self.client.session_transaction() as session:
            csrf_token = session["csrf_token"]

        for field, value, message, error_id in (
            ("email", "not-an-email", "メールアドレスを正しく入力してください。", "email-error"),
            ("phone", "abc", "電話番号を正しく入力してください。", "phone-error"),
        ):
            with self.subTest(field=field):
                data = {
                    "csrf_token": csrf_token,
                    "municipality": "深川市",
                    "consultation": "内容を確認したい",
                    "name": "テスト利用者",
                    "privacy_consent": "1",
                    field: value,
                }
                response = self.client.post("/solar/diagnosis", data=data)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn(message, html)
                self.assertIn(f'id="{error_id}"', html)

    def test_diagnosis_rejects_invalid_csrf_before_external_write(self):
        with patch.object(self.main, "track_solar_event") as track:
            response = self.client.post(
                "/solar/diagnosis",
                data={"csrf_token": "invalid-token"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertIn(
            "セキュリティ確認に失敗しました。",
            response.get_data(as_text=True),
        )
        names = [call.args[0] for call in track.call_args_list]
        self.assertIn("solar_diagnosis_validation_error", names)
        self.assertNotIn("solar_diagnosis_success", names)

    def test_diagnosis_success_emits_conversion_event_without_identifiers(self):
        self.client.get("/solar/diagnosis")
        with self.client.session_transaction() as session:
            csrf_token = session["csrf_token"]

        with patch.object(self.main, "track_solar_event") as track, patch.object(
            self.main, "create_case", return_value="case-not-in-event"
        ), patch.object(self.main, "update_case_column"), patch.object(
            self.main, "save_solar_customer_info"
        ), patch.object(
            self.main, "validate_solar_estimate_file", return_value=False
        ), patch.object(
            self.main,
            "save_solar_estimate_file",
            return_value={"filename": "", "storage_path": ""},
        ), patch.object(self.main, "save_solar_case_detail"), patch.object(
            self.main, "clear_sheet_request_cache"
        ):
            response = self.client.post(
                "/solar/diagnosis",
                data={
                    "csrf_token": csrf_token,
                    "municipality": "深川市",
                    "consultation": "内容を確認したい",
                    "name": "顧客氏名",
                    "email": "customer@example.test",
                    "privacy_consent": "1",
                },
            )

        self.assertEqual(response.status_code, 200)
        success_calls = [
            call for call in track.call_args_list
            if call.args[0] == "solar_diagnosis_success"
        ]
        self.assertEqual(len(success_calls), 1)
        self.assertNotIn("case-not-in-event", str(success_calls[0]))
        self.assertNotIn("customer@example.test", str(success_calls[0]))

    def test_compare_rejects_invalid_csrf_with_403_before_external_write(self):
        with patch.object(
            self.main,
            "get_solar_result_publication",
            return_value={
                "publish_status": "公開中",
                "case_id": "test-only-case",
            },
        ), patch.object(
            self.main,
            "validate_solar_result_publishable",
            return_value=({}, {}),
        ), patch.object(
            self.main,
            "build_solar_compare_share_snapshot",
            return_value={
                "name": "テスト利用者",
                "phone": "000-0000-0000",
                "email": "test@example.test",
                "municipality": "深川市",
            },
        ), patch.object(
            self.main,
            "get_solar_compare_request",
            return_value={},
        ), patch.object(
            self.main,
            "save_solar_compare_consent",
        ) as save_consent, patch.object(
            self.main,
            "withdraw_solar_compare_consent",
        ) as withdraw_consent:
            response = self.client.post(
                "/solar/result/test-only-token/compare",
                data={
                    "csrf_token": "invalid-token",
                    "action": "consent",
                    "share_consent": "yes",
                },
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn(
            "セキュリティ確認に失敗しました。",
            response.get_data(as_text=True),
        )
        save_consent.assert_not_called()
        withdraw_consent.assert_not_called()

    def test_compare_hides_unexpected_error_details(self):
        with patch.object(
            self.main,
            "get_solar_result_publication",
            return_value={
                "publish_status": "公開中",
                "case_id": "test-only-case",
            },
        ), patch.object(
            self.main,
            "validate_solar_result_publishable",
            return_value=({}, {}),
        ), patch.object(
            self.main,
            "build_solar_compare_share_snapshot",
            return_value={},
        ), patch.object(
            self.main,
            "get_solar_compare_request",
            return_value={},
        ), patch.object(
            self.main,
            "save_solar_compare_consent",
            side_effect=RuntimeError("internal secret details"),
        ):
            with self.client.session_transaction() as session:
                session["csrf_token"] = "valid-token"
            response = self.client.post(
                "/solar/result/test-only-token/compare",
                data={
                    "csrf_token": "valid-token",
                    "action": "consent",
                    "share_consent": "yes",
                },
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("処理中にエラーが発生しました。", html)
        self.assertNotIn("internal secret details", html)

    def test_line_ctas_when_configured(self):
        url = "https://line.example.test/solar-consultation"
        with patch.object(self.main, "SOLAR_LINE_ADD_URL", url):
            page = Page(self.solar_page())
        links = [a for a in page.attributes("a") if a.get("href") == url]
        self.assertEqual(len(links), 3)  # hero, final, sticky
        self.assertEqual(
            [a.get("data-solar-placement") for a in links],
            ["hero", "final", "sticky"],
        )
        for link in links:
            self.assertEqual(link.get("target"), "_blank")
            self.assertTrue({"noopener", "noreferrer"} <= set(link.get("rel", "").split()))
            self.assertEqual(link.get("data-solar-event"), "solar_line_cta_click")

    def test_line_ctas_hidden_when_environment_unset(self):
        self.assertEqual(self.main.SOLAR_LINE_ADD_URL, "")
        page = Page(self.solar_page())
        links = page.attributes("a")
        self.assertFalse(any("green" in a.get("class", "").split() for a in links))
        self.assertFalse(any("line" in a.get("href", "").lower() for a in links))
        for label in ("LINEで気軽に相談する", "LINEで相談する", "LINE相談"):
            self.assertNotIn(label, "".join(page.text))
        self.assertTrue(any(a.get("href") == "/solar/diagnosis" for a in links))

    def test_major_sections(self):
        html = self.solar_page()
        sections = {
            "trace-why": "その見積書、本当にそのまま契約して大丈夫ですか？",
            "trace-concerns": "こんなお悩みありませんか？",
            "trace-regret": "契約後に気づいても、変えにくいことがあります。",
            "trace-benefits": "見積書を確認すると、判断がこう変わります",
            "trace-checks": "8つのチェックポイント",
            "trace-flow": "診断の流れ",
            "trace-purpose": "売るためのサービスではありません。",
            "trace-reasons": "MITENOAが選ばれる理由",
            "trace-faq": "よくある質問",
            "trace-final": "まずは今の見積内容を整理しませんか？",
        }
        for css_class, heading in sections.items():
            with self.subTest(section=css_class):
                match = re.search(
                    r'<section\b[^>]*class="' + css_class + r'"[^>]*>(.*?)</section>',
                    html, re.S,
                )
                self.assertIsNotNone(match)
                page = Page(match.group(1))
                self.assertIn(heading, "".join(page.text))
                if css_class == "trace-purpose":
                    self.assertIn("施工会社側から紹介手数料を受け取る場合があります。", "".join(page.text))
                if css_class == "trace-checks":
                    self.assertEqual(sum(a.get("class") == "trace-check" for a in page.attributes("div")), 8)
                if css_class == "trace-final":
                    self.assertTrue(any(a.get("href") == "/solar/diagnosis" for a in page.attributes("a")))

    def assert_private_headers(self, response):
        self.assertIn("no-store", response.headers.get("Cache-Control", "").split(", "))
        self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")

    def test_public_result_headers_with_synthetic_record(self):
        with patch.object(self.main, "get_solar_result_publication", return_value={
            "publish_status": "公開中", "case_id": "test-only-case",
        }) as publication, patch.object(
            self.main, "validate_solar_result_publishable", return_value=({}, {})
        ) as validate, patch.object(
            self.main, "get_solar_detail_record", return_value={}
        ), patch.object(
            self.main, "get_solar_compare_request", return_value={}
        ), patch.object(self.main, "track_solar_event") as track:
            response = self.client.get("/solar/result/test-only-token")
        self.assertEqual(response.status_code, 200)
        publication.assert_called_once_with(token="test-only-token")
        validate.assert_called_once_with("test-only-case")
        self.assert_private_headers(response)
        self.assertIn(
            "solar_result_view",
            [call.args[0] for call in track.call_args_list],
        )

    def test_public_result_does_not_expose_detail_pii_or_raw_html(self):
        with patch.object(self.main, "get_solar_result_publication", return_value={
            "publish_status": "公開中", "case_id": "test-only-case",
        }), patch.object(
            self.main,
            "validate_solar_result_publishable",
            return_value=(
                {},
                {"missing_information": ["<script>alert(1)</script>"]},
            ),
        ), patch.object(
            self.main,
            "get_solar_detail_record",
            return_value={
                "municipality": "深川市",
                "name": "顧客氏名",
                "phone": "090-0000-0000",
                "email": "customer@example.test",
                "storage_path": "gs://internal-bucket/private.pdf",
            },
        ), patch.object(self.main, "get_solar_compare_request", return_value={}):
            response = self.client.get("/solar/result/test-only-token")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("顧客氏名", html)
        self.assertNotIn("090-0000-0000", html)
        self.assertNotIn("customer@example.test", html)
        self.assertNotIn("gs://internal-bucket/private.pdf", html)
        self.assertNotIn("<script>", html)

    def test_solar_upload_rejects_disallowed_extension(self):
        upload = FileStorage(
            stream=io.BytesIO(b"<svg></svg>"),
            filename="estimate.svg",
            content_type="image/svg+xml",
        )
        with self.assertRaises(ValueError):
            self.main.validate_solar_estimate_file(upload)

    def test_document_signing_fails_closed_without_key(self):
        with patch.object(self.main, "ADMIN_API_KEY", ""), patch.object(
            self.main.storage, "Client"
        ) as storage_client:
            self.assertIsNone(
                self.main.create_document_token("private/file.pdf")
            )
            self.assertEqual(
                self.main.build_document_url("private/file.pdf"),
                "",
            )
            response = self.client.get(
                "/document",
                query_string={
                    "path": "private/file.pdf",
                    "expires": "9999999999",
                    "sig": "empty-key-signature",
                },
            )

        self.assertEqual(response.status_code, 503)
        storage_client.assert_not_called()

    def test_document_signing_preserves_valid_key_and_rejects_bad_or_expired_links(self):
        class Blob:
            content_type = "application/pdf"

            def exists(self):
                return True

            def reload(self):
                return None

            def download_as_bytes(self):
                return b"%PDF-test"

        bucket = type("Bucket", (), {
            "blob": lambda self, _: Blob(),
        })()
        storage_client = type("StorageClient", (), {
            "bucket": lambda self, _: bucket,
        })()

        with patch.object(self.main, "ADMIN_API_KEY", "test-document-key"), patch.object(
            self.main.storage,
            "Client",
            return_value=storage_client,
        ):
            expires, signature = self.main.create_document_token(
                "private/file.pdf",
                valid_seconds=600,
            )
            response = self.client.get(
                "/document",
                query_string={
                    "path": "private/file.pdf",
                    "expires": expires,
                    "sig": signature,
                },
            )
            tampered = self.client.get(
                "/document",
                query_string={
                    "path": "private/other.pdf",
                    "expires": expires,
                    "sig": signature,
                },
            )
            expired = self.client.get(
                "/document",
                query_string={
                    "path": "private/file.pdf",
                    "expires": "1",
                    "sig": "expired-signature",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"%PDF-test")
        self.assertEqual(tampered.status_code, 403)
        self.assertEqual(expired.status_code, 403)

    def test_document_links_are_omitted_when_signing_is_unavailable(self):
        company = {
            "code": "A",
            "name": "会社A",
            "min": "1000000",
            "max": "1200000",
            "document": "private/file.pdf",
        }
        with patch.object(self.main, "ADMIN_API_KEY", ""), patch.object(
            self.main, "get_companies_from_row", return_value=[company]
        ):
            flex = self.main.build_comparison_flex("case-1", [])
            refresh = self.main.build_refresh_documents_flex("case-1", [])

        uri_actions = [
            item
            for item in flex["contents"]["body"]["contents"]
            if item.get("type") == "button"
            and item.get("action", {}).get("type") == "uri"
        ]
        self.assertEqual(uri_actions, [])
        self.assertIsNone(refresh)

    def test_solar_vendor_blank_token_is_private_404_without_sheet_access(self):
        with patch.object(self.main, "get_sheet_values") as get_values, patch.object(
            self.main, "update_sheet_range"
        ) as update_range:
            for token in ("", "   "):
                with self.subTest(token=repr(token)):
                    response = self.client.get(
                        "/solar/vendor/" + ("%20" if token else "")
                    )
                    self.assertEqual(response.status_code, 404)
                    if token:
                        self.assertEqual(
                            response.get_data(as_text=True),
                            "この閲覧URLは無効です。",
                        )

        get_values.assert_not_called()
        update_range.assert_not_called()

    def test_solar_vendor_valid_get_and_head_are_read_only(self):
        row = [
            "case-1", "A", "vendor-1", "会社A", "valid-token",
            "2026-01-01 00:00:00", "2099-01-01 00:00:00", "公開中",
            "2026-01-01 00:00:00", "", "old-access", "7",
            "contact-time", "v1",
        ]
        with patch.object(self.main, "get_sheet_values", return_value=[row]) as get_values, patch.object(
            self.main, "get_solar_compare_request",
            return_value={"request_status": "希望あり", "consent_status": "同意済み"},
        ), patch.object(
            self.main, "get_solar_vendor_assignments",
            return_value={"A": {"vendor_id": "vendor-1", "contact_status": "打診済み"}},
        ), patch.object(
            self.main, "get_solar_contact_event_for_publication",
            return_value={
                "estimate_document_shared": "いいえ",
                "consent_version": "v1",
                "shared_snapshot": {"name": "共有対象"},
            },
        ), patch.object(
            self.main, "validate_solar_contact_current_consent",
            return_value=True,
        ), patch.object(
            self.main, "build_solar_vendor_estimate_items",
            return_value=[],
        ), patch.object(
            self.main, "build_solar_vendor_diagnosis_items",
            return_value=[],
        ), patch.object(
            self.main, "update_sheet_range"
        ) as update_range, patch.object(
            self.main, "append_sheet_row"
        ) as append_row, patch.object(
            self.main, "track_solar_event"
        ) as track:
            response = self.client.get("/solar/vendor/valid-token")
            head = self.client.head("/solar/vendor/valid-token")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(get_values.call_count, 2)
        update_range.assert_not_called()
        append_row.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in track.call_args_list].count(
                "solar_vendor_view"
            ),
            2,
        )

    def test_solar_vendor_invalid_token_does_not_write(self):
        row = [
            "case-1", "A", "vendor-1", "会社A", "valid-token",
            "2026-01-01 00:00:00", "2099-01-01 00:00:00", "公開中",
            "2026-01-01 00:00:00", "", "old-access", "7",
            "contact-time", "v1",
        ]
        with patch.object(self.main, "get_sheet_values", return_value=[row]) as get_values, patch.object(
            self.main, "update_sheet_range"
        ) as update_range, patch.object(
            self.main, "append_sheet_row"
        ) as append_row, patch.object(
            self.main, "track_solar_event"
        ) as track:
            response = self.client.get("/solar/vendor/invalid-token")

        self.assertEqual(response.status_code, 404)
        get_values.assert_called_once()
        update_range.assert_not_called()
        append_row.assert_not_called()
        track.assert_not_called()

    def test_solar_public_read_only_flag_skips_sheet_ensure_writes(self):
        with self.main.app.test_request_context("/solar/vendor/valid-token"):
            self.main.g._solar_public_read_only = True
            with patch.object(self.main, "get_sheets_service") as sheets_service:
                self.main.ensure_solar_compare_sheet()
                self.main.ensure_solar_vendor_contact_sheet()
                self.main.ensure_solar_vendor_view_sheet()

        sheets_service.assert_not_called()

    def test_vendor_login_stores_auth_generation_and_stale_session_is_rejected(self):
        account = {
            "vendor_id": "vendor-1",
            "login_id": "login-1",
            "password_hash": self.main.generate_password_hash("password"),
            "enabled": True,
            "row_number": 2,
            "updated_at": "updated-1",
            "password_changed_at": "password-1",
        }
        vendor = {"vendor_id": "vendor-1", "status": "提携中"}
        with patch.object(
            self.main, "get_vendor_login_by_username", return_value=account
        ), patch.object(
            self.main, "get_vendor_master", return_value=[vendor]
        ), patch.object(
            self.main, "get_vendor_by_id", return_value=vendor
        ), patch.object(self.main, "update_sheet_range"):
            self.client.get("/vendor/login")
            with self.client.session_transaction() as session:
                csrf_token = session["csrf_token"]
            response = self.client.post(
                "/vendor/login",
                data={
                    "csrf_token": csrf_token,
                    "login_id": "login-1",
                    "password": "password",
                },
            )

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["vendor_account_updated_at"], "updated-1")
            self.assertEqual(session["vendor_password_changed_at"], "password-1")

        stale_account = dict(account, password_changed_at="password-2")
        with patch.object(self.main, "get_vendor_login_account", return_value=stale_account), patch.object(
            self.main, "get_vendor_master", return_value=[vendor]
        ), patch.object(
            self.main, "get_vendor_by_id", return_value=vendor
        ):
            response = self.client.get("/vendor/dashboard")

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("vendor_logged_in", session)

    def test_disabled_vendor_session_is_rejected_without_affecting_admin_session(self):
        with self.client.session_transaction() as session:
            session.update({
                "admin_logged_in": True,
                "vendor_logged_in": True,
                "vendor_id": "vendor-1",
                "vendor_account_updated_at": "updated-1",
                "vendor_password_changed_at": "password-1",
            })
        disabled = {
            "vendor_id": "vendor-1",
            "enabled": False,
            "updated_at": "updated-1",
            "password_changed_at": "password-1",
        }
        with patch.object(self.main, "get_vendor_login_account", return_value=disabled), patch.object(
            self.main, "get_vendor_master", return_value=[{"vendor_id": "vendor-1", "status": "提携中"}]
        ), patch.object(
            self.main, "get_vendor_by_id", return_value={"vendor_id": "vendor-1", "status": "提携中"}
        ):
            response = self.client.get("/vendor/dashboard")

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertTrue(session.get("admin_logged_in"))
            self.assertNotIn("vendor_logged_in", session)

    def test_stopped_partner_cannot_overwrite_consent_state(self):
        stopped = {
            "vendor_id": "vendor-1",
            "status": "停止",
            "terms_version": "1.0",
            "meeting_date": "2026-01-01",
            "online_consent_at": "",
        }
        with patch.object(self.main, "ensure_vendor_admin_sheets") as ensure_admin, patch.object(
            self.main, "get_vendor_master", return_value=[stopped]
        ), patch.object(
            self.main, "get_vendor_by_id", return_value=stopped
        ), patch.object(self.main, "update_sheet_range") as update_range, patch.object(
            self.main, "record_vendor_consent_history"
        ) as record_history:
            response = self.client.post(
                "/partner/consent/vendor-1",
                data={
                    "token": "synthetic-token",
                    "confirm_terms": "1",
                    "confirm_meeting": "1",
                    "confirm_fee": "1",
                    "confirm_privacy": "1",
                    "confirm_question": "1",
                    "confirm_agree": "1",
                    "consent_name": "同意者",
                },
            )

        self.assertEqual(response.status_code, 403)
        ensure_admin.assert_not_called()
        update_range.assert_not_called()
        record_history.assert_not_called()

    def test_enabled_partner_consent_flow_still_updates_state(self):
        enabled = {
            "vendor_id": "vendor-1",
            "status": "提携中",
            "terms_version": "1.0",
            "meeting_date": "2026-01-01",
            "online_consent_at": "",
            "row_number": 2,
        }
        with patch.object(self.main, "ensure_vendor_admin_sheets"), patch.object(
            self.main, "get_vendor_master", return_value=[enabled]
        ), patch.object(
            self.main, "get_vendor_by_id", return_value=enabled
        ), patch.object(
            self.main, "verify_partner_consent_token", return_value=True
        ), patch.object(self.main, "update_sheet_range") as update_range, patch.object(
            self.main, "record_vendor_consent_history"
        ) as record_history:
            response = self.client.post(
                "/partner/consent/vendor-1",
                data={
                    "token": "synthetic-token",
                    "confirm_terms": "1",
                    "confirm_meeting": "1",
                    "confirm_fee": "1",
                    "confirm_privacy": "1",
                    "confirm_question": "1",
                    "confirm_agree": "1",
                    "consent_name": "同意者",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(update_range.called)
        record_history.assert_called_once()

    def test_unknown_or_revoked_result_is_private_404(self):
        for record in (None, {"publish_status": "公開停止", "case_id": "test-only-case"}):
            with self.subTest(record=record), patch.object(
                self.main, "get_solar_result_publication", return_value=record
            ) as publication, patch.object(
                self.main, "validate_solar_result_publishable"
            ) as validate, patch.object(
                self.main, "track_solar_event"
            ) as track:
                response = self.client.get("/solar/result/test-only-token")
                self.assertEqual(response.status_code, 404)
                self.assert_private_headers(response)
                publication.assert_called_once_with(token="test-only-token")
                validate.assert_not_called()
                track.assert_not_called()


if __name__ == "__main__":
    unittest.main()
