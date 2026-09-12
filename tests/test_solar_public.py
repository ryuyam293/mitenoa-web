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

    def test_solar_returns_200_and_diagnosis_ctas(self):
        links = Page(self.solar_page()).attributes("a")
        diagnosis = [a for a in links if a.get("href") == "/solar/diagnosis"]
        self.assertEqual(len(diagnosis), 4)  # header, hero, final, sticky

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
        response = self.client.post(
            "/solar/diagnosis",
            data={"csrf_token": "invalid-token"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(
            "セキュリティ確認に失敗しました。",
            response.get_data(as_text=True),
        )

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
        for link in links:
            self.assertEqual(link.get("target"), "_blank")
            self.assertTrue({"noopener", "noreferrer"} <= set(link.get("rel", "").split()))

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
        ), patch.object(self.main, "get_solar_compare_request", return_value={}):
            response = self.client.get("/solar/result/test-only-token")
        self.assertEqual(response.status_code, 200)
        publication.assert_called_once_with(token="test-only-token")
        validate.assert_called_once_with("test-only-case")
        self.assert_private_headers(response)

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

    def test_unknown_or_revoked_result_is_private_404(self):
        for record in (None, {"publish_status": "公開停止", "case_id": "test-only-case"}):
            with self.subTest(record=record), patch.object(
                self.main, "get_solar_result_publication", return_value=record
            ) as publication, patch.object(self.main, "validate_solar_result_publishable") as validate:
                response = self.client.get("/solar/result/test-only-token")
                self.assertEqual(response.status_code, 404)
                self.assert_private_headers(response)
                publication.assert_called_once_with(token="test-only-token")
                validate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
