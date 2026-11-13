"""Serve actual persisted campaigns through the production API on loopback."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
from phase65_fixtures import SCENARIOS, generate_campaign
from pentest_pipeline import web_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--phase7", action="store_true")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    manifest = args.directory / "cases.json"
    if args.reuse:
        cases = json.loads(manifest.read_text())
    else:
        assert not manifest.exists(), "Do not overwrite a prior acceptance run"
        cases = [generate_campaign(args.directory, scenario, phase7=args.phase7) for scenario in SCENARIOS]
        manifest.write_text(json.dumps(cases, indent=2))
    web_server.REPORTS = args.directory / "reports"
    console = web_server.CampaignConsole(args.directory / "scope.json")
    server = web_server.ConsoleHTTPServer(("127.0.0.1", 0), console)
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "cases": cases}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
