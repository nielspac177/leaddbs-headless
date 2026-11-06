# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2"]
# ///
"""End-to-end smoke test over real MCP stdio.

Usage: uv run headless/tests/smoke_test.py /path/to/dataset [--matlab]

Without --matlab: checks the tool list, list_subjects, get_status, input
validation and the PHI scrubber. With --matlab: also runs
run_preprocessing(dry_run=True) and waits for MATLAB to build the options.
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent.parent / "server" / "leaddbs_mcp.py"


def leaks(text, raw_ids):
    """True if a raw BIDS ID appears as a whole token (not inside a timestamp)."""
    return any(re.search(rf"(?<![A-Za-z0-9]){re.escape(r)}(?![A-Za-z0-9])", text) for r in raw_ids)


def payload(result):
    return json.loads(result.content[0].text)


async def main(dataset: str, with_matlab: bool) -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                   env={**os.environ, "LEADDBS_DATASET": dataset})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        tools = sorted(t.name for t in (await s.list_tools()).tools)
        assert tools == ["get_status", "list_subjects", "run_preprocessing"], tools
        print("tools:", tools)

        subjects = payload(await s.call_tool("list_subjects", {}))
        print("list_subjects:", json.dumps(subjects))
        raw_ids = [p.name[4:] for p in Path(dataset, "rawdata").glob("sub-*")]
        text = json.dumps(subjects)
        assert not leaks(text, raw_ids), "real ID leaked"

        bad = await s.call_tool("run_preprocessing", {"subject_id": "sub-01"})
        assert bad.isError, "schema did not reject a raw ID"
        bad = await s.call_tool("run_preprocessing",
                                {"subject_id": subjects["subjects"][0]["id"],
                                 "electrode_model": "Made Up 9000"})
        assert bad.isError, "schema did not reject an unknown electrode"
        print("validation: raw IDs and unknown electrode models rejected")

        target = next(x for x in subjects["subjects"] if x["has_postop_imaging"])
        print("get_status:", json.dumps(payload(await s.call_tool(
            "get_status", {"subject_id": target["id"]}))))

        if with_matlab:
            # Only subjects that never ran: a new job hides the results of an old one.
            started, refusals = None, 0
            for x in (y for y in subjects["subjects"] if y["last_run_state"] is None):
                target = x
                args = {"subject_id": x["id"], "dry_run": True}
                started = payload(await s.call_tool(
                    "run_preprocessing", {**args, "electrode_model": "Medtronic 3389"}))
                print("run_preprocessing:", started)
                if started["accepted"]:
                    break
                refusals += 1
                if started["reason"] == "electrode_model_mismatch":
                    started = payload(await s.call_tool(
                        "run_preprocessing", {**args, "electrode_model": started["stored_model"]}))
                    print("run_preprocessing with stored model:", started)
                    break
            assert refusals, "no request was refused"
            assert started and started["accepted"], "no subject could start a dry run"
            for _ in range(120):
                status = payload(await s.call_tool("get_status", {"subject_id": target["id"]}))
                if status["state"] in ("finished", "failed"):
                    break
                time.sleep(5)
            print("get_status after run:", json.dumps(status, indent=1))
            assert not leaks(json.dumps(status), raw_ids), "real ID leaked"
            print("no raw IDs in any tool output")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], "--matlab" in sys.argv))
