"""Verify that the operator stop path preserves a partial campaign."""

import base64
import json
import http.client
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pentest_pipeline.web_server import CampaignConsole, ConsoleHTTPServer


class _StoppedResult:
    def to_dict(self):
        return {
            "run_id": "local-stop-test",
            "target": "https://4.migbot.com.br/",
            "campaign_name": "test",
            "started_at": "2026-11-12T00:00:00+00:00",
            "ended_at": "2026-11-12T00:00:01+00:00",
            "status": "stopped",
            "stop_reason": "operator_requested",
            "actions": [{"timestamp": "2026-11-12T00:00:00+00:00", "type": "request", "phase": "discovery", "message": "Synthetic request"}],
            "findings": [],
            "recommendations": [],
            "summary": {"requests": 1, "findings": 0},
        }


class WebConsoleStopTests(unittest.TestCase):
    def test_stop_preserves_result_and_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "scope.json"
            config_file.write_text(json.dumps({
                "target_url": "https://4.migbot.com.br/#/",
                "allowed_hosts": ["4.migbot.com.br"],
            }))

            def fake_scan(config, *, stop_event, on_event, ai_advisor, ai_planner,
                          ai_target_reviewer, approval_queue, checkpoint_store=None, cve_intelligence=False, ai_planning=False, planning_provider=None, container_execution=None):
                on_event({"timestamp": "2026-11-12T00:00:00+00:00", "type": "request", "phase": "discovery", "message": "Synthetic request"})
                self.assertTrue(stop_event.wait(2), "the stop signal never reached the scan")
                return _StoppedResult()

            with patch("pentest_pipeline.web_server.REPORTS", root / "reports"), patch(
                "pentest_pipeline.web_server.run_campaign", side_effect=fake_scan
            ):
                console = CampaignConsole(config_file)
                self.assertTrue(console.start()[0])
                self.assertFalse(console.start()[0])
                self.assertTrue(console.stop()[0])
                deadline = time.monotonic() + 3
                while console.snapshot()["running"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                snapshot = console.snapshot()
                self.assertFalse(snapshot["running"])
                self.assertEqual(snapshot["result"]["status"], "stopped")
                self.assertEqual(snapshot["result"]["stop_reason"], "operator_requested")
                self.assertTrue((root / "reports" / "local-stop-test" / "result.json").is_file())
                self.assertTrue(any(item["phase"] == "stop" for item in snapshot["events"]))


class WebConsoleHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reports = self.root / "reports"
        self.reports.mkdir()
        config = self.root / "scope.json"
        config.write_text(json.dumps({"target_url": "https://example.org/",
                                      "allowed_hosts": ["example.org"]}), encoding="utf-8")
        patcher = patch("pentest_pipeline.web_server.REPORTS", self.reports)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.console = CampaignConsole(config)
        self.server = ConsoleHTTPServer(("127.0.0.1", 0), self.console)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)

    def get(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def save(self, run_id, date, filename="evidence.json"):
        payload = _StoppedResult().to_dict()
        payload.update(run_id=run_id, started_at=date, target=f"https://{run_id}.example.org/")
        directory = self.reports / run_id
        directory.mkdir()
        (directory / filename).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def test_history_orders_saved_runs_and_opens_exact_result_without_changing_live_state(self):
        older = self.save("older", "2026-11-11T00:00:00+00:00", "result.json")
        self.save("newer", "2026-11-12T00:00:00+00:00")
        status, history = self.get("/api/history")
        self.assertEqual(status, 200)
        self.assertEqual([item["run_id"] for item in history["runs"]], ["newer", "older"])
        self.assertEqual(history["warnings"], [])
        self.assertEqual(history["runs"][0]["findings_count"], 0)
        self.console.running = True
        self.console.result = {"run_id": "live"}
        status, detail = self.get("/api/history/older")
        self.assertEqual(status, 200)
        self.assertEqual({k: detail["result"][k] for k in older}, older)
        self.assertEqual(detail["result"]["execution_status"], "cancelled")
        self.assertEqual(detail["result"]["assessment_status"], "blocked")
        self.assertEqual(json.loads((self.reports / "older" / "result.json").read_text()), older)
        self.assertTrue(self.console.running)
        self.assertEqual(self.console.result, {"run_id": "live"})

    def test_history_rejects_missing_and_traversal_paths(self):
        self.assertEqual(self.get("/api/history")[1]["runs"], [])
        for path in ("missing", "../scope", "%2e%2e%2f.env", "older/result.json"):
            with self.subTest(path=path):
                self.assertEqual(self.get(f"/api/history/{path}")[0], 404)

    def test_checkpoint_directory_is_not_a_saved_campaign(self):
        (self.reports / "checkpoints").mkdir()
        self.save("valid", "2026-11-13T00:00:00+00:00")
        status, payload = self.get("/api/history")
        self.assertEqual(status, 200)
        self.assertEqual(payload["warnings"], [])
        self.assertEqual([r["run_id"] for r in payload["runs"]], ["valid"])

    def test_execution_and_hypothesis_api_survive_console_restart(self):
        from pentest_pipeline.orchestration.event_store import EventStore
        payload = self.save("verifiable", "2026-11-13T00:00:00+00:00", "result.json")
        hypothesis = {"hypothesis_id": "h1", "campaign_id": "verifiable", "vulnerability_id": "CVE-FIXTURE",
                      "component_id": "c1", "correlation_status": "candidate", "evidence_refs": ["e1"]}
        store = EventStore("verifiable")
        for item in [
            {"type": "hypothesis_registered", "hypothesis": hypothesis},
            {"type": "evidence_registered", "evidence": {"evidence_id": "e1", "title": "Fixture", "raw_body": "not-for-ui"}},
            {"type": "validation_started", "task_id": "t1", "validation_id": "v1", "hypothesis_id": "h1",
             "isolation_level": "none", "evidence_refs": ["e1"]},
            {"type": "validation_completed", "task_id": "t1", "validation_id": "v1", "status": "completed",
             "validation_status": "inconclusive"}]:
            store.append(item)
        payload["execution_events"] = store.all()
        (self.reports / "verifiable" / "result.json").write_text(json.dumps(payload))
        restarted = CampaignConsole(self.console.config_path)
        snapshot = restarted.snapshot()
        status, saved = self.get("/api/history/verifiable")
        self.assertEqual(status, 200)
        self.assertEqual(snapshot["executions"], saved["executions"])
        self.assertEqual(snapshot["hypotheses"], saved["hypotheses"])
        row = saved["executions"][0]
        self.assertEqual((row["execution_status"], row["validation_status"]), ("completed", "inconclusive"))
        self.assertEqual(row["execution_backend"], "simulated")
        self.assertEqual(row["evidence_refs"], ["e1"])
        self.assertNotIn("raw_body", saved["evidence_catalog"][0])

    def test_live_hypothesis_is_visible_before_any_validation(self):
        self.console.running = True
        self.console._record({"type": "hypothesis_registered", "hypothesis": {
            "hypothesis_id": "candidate", "correlation_status": "version_unknown"}})
        status, payload = self.get("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["executions"], [])
        self.assertEqual(payload["hypotheses"][0]["correlation_status"], "version_unknown")

    def test_history_surfaces_unreadable_report_without_hiding_valid_runs(self):
        self.save("valid", "2026-11-12T00:00:00+00:00")
        broken = self.reports / "broken"
        broken.mkdir()
        (broken / "evidence.json").write_text("{", encoding="utf-8")
        malformed = self.save("malformed", 123)
        status, history = self.get("/api/history")
        self.assertEqual(status, 200)
        self.assertEqual(len(history["runs"]), 1)
        self.assertEqual(len(history["warnings"]), 2)
        self.assertTrue(any("broken" in warning for warning in history["warnings"]))
        self.assertEqual(self.get("/api/history/broken")[0], 500)
        self.assertEqual(self.get(f"/api/history/{malformed['run_id']}")[0], 500)


class WebConsoleInputTests(unittest.TestCase):
    def test_post_requires_authorization_and_ai_key_then_uses_submitted_url(self):
        secret = "sk-test-only-never-log"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "scope.json"
            config_file.write_text(json.dumps({
                "target_url": "https://4.migbot.com.br/#/",
                "allowed_hosts": ["4.migbot.com.br"],
            }), encoding="utf-8")
            seen = []

            class _CompletedResult:
                def to_dict(self):
                    return {
                        "run_id": "dynamic-url-test", "target": seen[-1],
                        "campaign_name": "test", "status": "completed",
                        "started_at": "2026-11-12T00:00:00+00:00",
                        "ended_at": "2026-11-12T00:00:01+00:00",
                        "stop_reason": "planned_tests_complete", "actions": [],
                        "findings": [], "observations": [], "recommendations": [],
                        "summary": {"requests": 1, "findings": 0},
                    }

            def fake_scan(config, *, stop_event, on_event, ai_advisor, ai_planner,
                          ai_target_reviewer, approval_queue, checkpoint_store=None, cve_intelligence=False, ai_planning=False, planning_provider=None, container_execution=None):
                seen.append(config.target_url)
                self.assertIsNotNone(ai_planner)
                self.assertIsNotNone(ai_advisor)
                self.assertIsNotNone(ai_target_reviewer)
                self.assertIsNotNone(approval_queue)
                return _CompletedResult()

            with patch("pentest_pipeline.web_server.REPORTS", root / "reports"), patch(
                "pentest_pipeline.web_server.run_campaign", side_effect=fake_scan
            ), patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
                console = CampaignConsole(config_file)
                server = ConsoleHTTPServer(("127.0.0.1", 0), console)
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    def post(payload):
                        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                        connection.request("POST", "/api/campaign/start",
                                           body=json.dumps(payload),
                                           headers={"Content-Type": "application/json",
                                                    "Origin": f"http://127.0.0.1:{server.server_port}"})
                        response = connection.getresponse()
                        status = response.status
                        data = json.loads(response.read())
                        connection.close()
                        return status, data

                    target = "https://4.migbot.com.br//#/tokensale-ico-ea"
                    self.assertEqual(post({"target_url": target, "api_key": secret})[0], 400)
                    self.assertEqual(post({"target_url": target,
                                           "authorization_confirmed": True})[0], 400)
                    self.assertEqual(post({"target_url": "https://localhost/",
                                           "api_key": secret,
                                           "authorization_confirmed": True})[0], 400)
                    status, _ = post({"target_url": target, "api_key": secret,
                                      "authorization_confirmed": True})
                    self.assertEqual(status, 202)
                    deadline = time.monotonic() + 3
                    while console.snapshot()["running"] and time.monotonic() < deadline:
                        time.sleep(0.01)
                    snapshot = console.snapshot()
                    self.assertEqual(seen, ["https://4.migbot.com.br//"])
                    self.assertEqual(snapshot["scope"]["target"], seen[0])
                    self.assertEqual(snapshot["result"]["status"], "completed")
                    self.assertNotIn(secret, json.dumps(snapshot))
                    self.assertNotIn(secret, (root / "reports" / "dynamic-url-test" / "result.json").read_text())
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(timeout=3)

    def test_post_accepts_bedrock_api_key_without_persisting_it(self):
        secret = "bedrock-api-key-test-only"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "scope.json"
            config_file.write_text(json.dumps({
                "target_url": "https://4.migbot.com.br/",
                "allowed_hosts": ["4.migbot.com.br"],
            }), encoding="utf-8")
            observed = {}

            class Result:
                def to_dict(self):
                    return {"run_id": "bedrock-web-test", "target": "https://4.migbot.com.br/",
                            "campaign_name": "test", "status": "completed",
                            "started_at": "2026-11-12T00:00:00+00:00",
                            "ended_at": "2026-11-12T00:00:01+00:00",
                            "stop_reason": "planned_tests_complete", "actions": [],
                            "findings": [], "observations": [], "recommendations": [],
                            "summary": {"requests": 0, "findings": 0}}

            def fake_components(**options):
                observed.update(options)
                return (object(), object(), object())

            def fake_scan(config, *, stop_event, on_event, ai_advisor, ai_planner,
                          ai_target_reviewer, approval_queue, checkpoint_store=None, cve_intelligence=False, ai_planning=False, planning_provider=None, container_execution=None):
                return Result()

            with patch("pentest_pipeline.web_server.REPORTS", root / "reports"), patch(
                "pentest_pipeline.web_server.create_ai_components", side_effect=fake_components
            ), patch("pentest_pipeline.web_server.run_campaign", side_effect=fake_scan):
                console = CampaignConsole(config_file)
                server = ConsoleHTTPServer(("127.0.0.1", 0), console)
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    connection.request("POST", "/api/campaign/start", body=json.dumps({
                        "target_url": "https://4.migbot.com.br/",
                        "api_key": secret,
                        "authorization_confirmed": True,
                        "ai_provider": "bedrock",
                        "ai_model": "amazon.nova-micro-v1:0",
                        "aws_region": "us-east-1",
                    }), headers={"Content-Type": "application/json",
                                 "Origin": f"http://127.0.0.1:{server.server_port}"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 202)
                    response.read()
                    connection.close()
                    deadline = time.monotonic() + 3
                    while console.snapshot()["running"] and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(observed["provider"], "bedrock")
                    self.assertEqual(observed["model"], "amazon.nova-micro-v1:0")
                    self.assertEqual(observed["region"], "us-east-1")
                    self.assertEqual(observed["api_key"], secret)
                    self.assertNotIn(secret, json.dumps(console.snapshot()))
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(timeout=3)


class WebConsoleEvidenceTests(unittest.TestCase):
    def test_evidence_route_serves_only_local_png_files(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl1GDsAAAAASUVORK5CYII="
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "ftp-listagem.png").write_bytes(png)
            (evidence / "bad.png").write_text("<script>alert(1)</script>", encoding="utf-8")
            (root / "secret.png").write_bytes(png)
            (evidence / "outside.png").symlink_to(root / "secret.png")
            config_file = root / "scope.json"
            config_file.write_text(json.dumps({
                "target_url": "https://4.migbot.com.br/#/",
                "allowed_hosts": ["4.migbot.com.br"],
            }), encoding="utf-8")

            with patch("pentest_pipeline.web_server.EVIDENCE", evidence), patch(
                "pentest_pipeline.web_server.REPORTS", root / "reports"
            ):
                server = ConsoleHTTPServer(("127.0.0.1", 0), CampaignConsole(config_file))
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    def get(path, *, host=None):
                        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                        headers = {"Host": host} if host else {}
                        connection.request("GET", path, headers=headers)
                        response = connection.getresponse()
                        result = (response.status, response.getheader("Content-Type"),
                                  response.getheader("X-Content-Type-Options"), response.read())
                        connection.close()
                        return result

                    status, content_type, nosniff, body = get("/evidence/ftp-listagem.png")
                    self.assertEqual((status, content_type, nosniff, body),
                                     (200, "image/png", "nosniff", png))
                    for path in (
                        "/evidence/../secret.png", "/evidence/%2e%2e/secret.png",
                        "/evidence/ftp-listagem.png?download=1", "/evidence/ftp-listagem.png#fragment",
                        "/evidence/invalid.svg", "/evidence/bad.png", "/evidence/outside.png",
                        "/evidence/a..png",
                    ):
                        with self.subTest(path=path):
                            self.assertEqual(get(path)[0], 404)
                    self.assertEqual(get("/evidence/ftp-listagem.png", host="elsewhere.example")[0], 403)
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(timeout=3)


class WebConsoleFrontendSeparationTests(unittest.TestCase):
    def test_python_server_exposes_api_but_does_not_serve_frontend_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "scope.json"
            config_file.write_text(json.dumps({
                "target_url": "https://4.migbot.com.br/",
                "allowed_hosts": ["4.migbot.com.br"],
            }), encoding="utf-8")

            server = ConsoleHTTPServer(("127.0.0.1", 0), CampaignConsole(config_file))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                def get(path):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    connection.request("GET", path)
                    response = connection.getresponse()
                    result = (response.status, response.getheader("Content-Type"), response.read())
                    connection.close()
                    return result

                self.assertEqual(get("/api/status")[0], 200)
                for path in ("/", "/app.js", "/style.css", "/assets/app.js"):
                    with self.subTest(path=path):
                        self.assertEqual(get(path)[0], 404)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)


class WebConsoleApprovalTests(unittest.TestCase):
    def test_conditional_action_waits_for_local_approval_and_is_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "scope.json"
            config_file.write_text(json.dumps({
                "target_url": "https://4.migbot.com.br/",
                "allowed_hosts": ["4.migbot.com.br"],
                "search_path": "/rest/products/search",
            }), encoding="utf-8")

            class Result:
                def to_dict(self):
                    return {"run_id": "approval-test", "target": "https://4.migbot.com.br/",
                            "campaign_name": "test", "status": "completed",
                            "started_at": "2026-11-12T00:00:00+00:00",
                            "ended_at": "2026-11-12T00:00:01+00:00",
                            "stop_reason": "planned_tests_complete", "actions": [],
                            "findings": [], "observations": [], "recommendations": [],
                            "summary": {"requests": 0, "findings": 0}}

            def fake_scan(config, *, stop_event, on_event, ai_advisor, ai_planner,
                          ai_target_reviewer, approval_queue, checkpoint_store=None, cve_intelligence=False, ai_planning=False, planning_provider=None, container_execution=None):
                self.assertTrue(approval_queue.require(
                    "quoted_search", target="https://4.migbot.com.br/rest/products/search",
                    reason="Comparação sintética", stop_event=stop_event))
                return Result()

            with patch("pentest_pipeline.web_server.REPORTS", root / "reports"), patch(
                "pentest_pipeline.web_server.run_campaign", side_effect=fake_scan
            ):
                console = CampaignConsole(config_file)
                server = ConsoleHTTPServer(("127.0.0.1", 0), console)
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    self.assertTrue(console.start()[0])
                    deadline = time.monotonic() + 3
                    while not console.snapshot()["approvals"] and time.monotonic() < deadline:
                        time.sleep(0.01)
                    pending = console.snapshot()["approvals"]
                    self.assertEqual(len(pending), 1)
                    self.assertEqual(pending[0]["status"], "pending")
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    connection.request("POST", "/api/approval/decision",
                                       body=json.dumps({"approval_id": pending[0]["id"], "approve": True}),
                                       headers={"Content-Type": "application/json",
                                                "Origin": f"http://127.0.0.1:{server.server_port}"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 202)
                    response.read()
                    connection.close()
                    while console.snapshot()["running"] and time.monotonic() < deadline:
                        time.sleep(0.01)
                    snapshot = console.snapshot()
                    self.assertFalse(snapshot["running"])
                    self.assertEqual(snapshot["approvals"][0]["status"], "approved")
                    report = snapshot["result"]
                    self.assertEqual([event["status"] for event in report["actions"]
                                      if event.get("type") == "approval"], ["pending", "approved"])
                    self.assertIn("decisão approved", (root / "reports" / "approval-test" / "report.md").read_text())
                finally:
                    console.stop()
                    server.shutdown()
                    server.server_close()
                    worker.join(timeout=3)


class WebConsoleLoadedReportTests(unittest.TestCase):
    def test_cli_report_keeps_its_target_and_json_download_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "scope.json"
            config_file.write_text(json.dumps({
                "target_url": "https://4.migbot.com.br/",
                "allowed_hosts": ["4.migbot.com.br"],
            }), encoding="utf-8")
            report_dir = root / "reports" / "prior-run"
            report_dir.mkdir(parents=True)
            payload = {
                "run_id": "prior-run", "target": "https://4.migbot.com.br/ftp/",
                "status": "completed", "actions": [], "findings": [], "observations": [],
                "summary": {"scope": {"target": "https://4.migbot.com.br/ftp/",
                                      "allowed_methods": ["GET", "HEAD"],
                                      "max_requests": 11, "min_interval_seconds": 1.0,
                                      "max_response_bytes": 524288,
                                      "conditional_actions": ["quoted_search"]}},
            }
            (report_dir / "evidence.json").write_text(json.dumps(payload), encoding="utf-8")
            (report_dir / "report.md").write_text("# Prior run\n", encoding="utf-8")
            with patch("pentest_pipeline.web_server.REPORTS", root / "reports"):
                console = CampaignConsole(config_file)
                self.assertEqual(console.snapshot()["scope"]["target"], payload["target"])
                server = ConsoleHTTPServer(("127.0.0.1", 0), console)
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    connection.request("GET", "/api/report.json")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["run_id"], "prior-run")
                    connection.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
