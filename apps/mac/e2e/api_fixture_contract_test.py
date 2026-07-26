from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from packages.contracts.quant.csv_market_data import parse_market_ohlcv_csv
from packages.contracts.quant.market_data import QuantBarInterval
from packages.contracts.quant.schemas import (
    QuantMarketBinanceFetchRequest,
    QuantMarketDatasetV2PreviewResponse,
    QuantMarketDatasetV2Response,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "apps" / "mac" / "e2e" / "api-fixture.mjs"
WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"
ACCESS_TOKEN = "fixture-contract-token"


def build_btcusdt_1d_csv(count: int = 365) -> str:
    start = 1672531200
    rows = ["timestamp,open,high,low,close,volume"]
    for index in range(count):
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + index * 86400))
        base = 16500 + index * 12
        open_price = base + (index % 5)
        close_price = base + 6 + (index % 7)
        high = max(open_price, close_price) + 9
        low = min(open_price, close_price) - 8
        volume = 1000 + index * 3
        rows.append(
            f"{timestamp},{open_price:.2f},{high:.2f},{low:.2f},{close_price:.2f},{volume:.2f}"
        )
    return "\n".join(rows)


def rewrite_csv_close(csv_text: str, row_number: int, close_price: float) -> str:
    lines = csv_text.splitlines()
    cells = lines[row_number].split(",")
    open_price = float(cells[1])
    high = max(float(cells[2]), close_price)
    low = min(float(cells[3]), close_price)
    lines[row_number] = ",".join(
        [
            cells[0],
            f"{open_price:.2f}",
            f"{high:.2f}",
            f"{low:.2f}",
            f"{close_price:.2f}",
            f"{float(cells[5]):.2f}",
        ]
    )
    return "\n".join(lines)


class ApiFixtureContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        env = os.environ.copy()
        env["GLINT_FIXTURE_PORT"] = str(cls.port)
        env["GLINT_FIXTURE_ACCESS_TOKEN"] = ACCESS_TOKEN
        env["GLINT_FIXTURE_ALLOWED_ORIGIN"] = "http://127.0.0.1:5173"
        cls.server = subprocess.Popen(
            ["node", str(FIXTURE)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                cls.request_json("GET", "/quant/datasets/v2")
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("Fixture server did not start in time.")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def request_json(cls, method: str, path: str, body: dict | None = None):
        request = Request(
            f"http://127.0.0.1:{cls.port}{path}",
            method=method,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json",
                "Idempotency-Key": "contract-test-key",
                "X-Workspace-ID": WORKSPACE_ID,
                "X-Fixture-Contract-Mode": "response-model",
            },
        )
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_market_v2_fixture_responses_validate_against_real_models(self) -> None:
        _, listed = self.request_json("GET", "/quant/datasets/v2")
        for row in listed:
            QuantMarketDatasetV2Response.model_validate(row)

        payload = {
            "name": "BTCUSDT Binance Spot 1 day",
            "symbol": "BTCUSDT",
            "interval": "1D",
            "limit": 365,
        }
        QuantMarketBinanceFetchRequest.model_validate(payload)
        status, response = self.request_json("POST", "/quant/datasets/v2/fetch-binance", payload)
        self.assertEqual(status, 201)
        dataset = QuantMarketDatasetV2Response.model_validate(response)
        self.assertEqual(str(dataset.workspace_id), WORKSPACE_ID)
        self.assertEqual(dataset.bar_count, 365)
        self.assertEqual(dataset.evidence.requested_bar_count, 365)
        self.assertEqual(dataset.evidence.returned_bar_count, 365)
        self.assertEqual(dataset.evidence.retained_bar_count, 365)
        self.assertEqual(len(dataset.evidence.page_raw_sha256), 1)

        _, preview_response = self.request_json(
            "GET", f"/quant/datasets/v2/{dataset.dataset_id}/preview?max_points=240"
        )
        preview = QuantMarketDatasetV2PreviewResponse.model_validate(preview_response)
        self.assertEqual(preview.dataset.dataset_id, dataset.dataset_id)
        self.assertEqual(preview.total_bar_count, 365)

        first_csv = build_btcusdt_1d_csv()
        second_csv = rewrite_csv_close(first_csv, 40, 18888)
        expected_first = parse_market_ohlcv_csv(
            first_csv, symbol="BTCUSDT", interval=QuantBarInterval.DAILY
        )
        expected_second = parse_market_ohlcv_csv(
            second_csv, symbol="BTCUSDT", interval=QuantBarInterval.DAILY
        )

        payload = {
            "name": "BTCUSDT CSV 1 day",
            "symbol": "BTCUSDT",
            "interval": "1D",
            "csv_text": first_csv,
            "file_name": "btcusdt-1d.csv",
            "source_name": "Research CSV",
            "source_reference": "upload:btc-1d",
        }
        _, first_response = self.request_json("POST", "/quant/datasets/v2/import-csv", payload)
        _, same_response = self.request_json("POST", "/quant/datasets/v2/import-csv", payload)
        _, second_response = self.request_json(
            "POST",
            "/quant/datasets/v2/import-csv",
            {
                **payload,
                "name": "BTCUSDT CSV 1 day B",
                "csv_text": second_csv,
                "source_reference": "upload:btc-1d-b",
            },
        )
        first_dataset = QuantMarketDatasetV2Response.model_validate(first_response)
        same_dataset = QuantMarketDatasetV2Response.model_validate(same_response)
        second_dataset = QuantMarketDatasetV2Response.model_validate(second_response)
        self.assertEqual(first_dataset.dataset_id, expected_first.dataset_id)
        self.assertEqual(same_dataset.dataset_id, expected_first.dataset_id)
        self.assertEqual(first_dataset.dataset_id, same_dataset.dataset_id)
        self.assertNotEqual(second_dataset.dataset_id, first_dataset.dataset_id)
        self.assertEqual(second_dataset.dataset_id, expected_second.dataset_id)

        with self.assertRaises(HTTPError) as conflict:
            self.request_json(
                "POST",
                "/quant/datasets/v2/import-csv",
                {**payload, "source_reference": "upload:btc-1d-different-evidence"},
            )
        self.assertEqual(conflict.exception.code, 409)

        _, first_preview_response = self.request_json(
            "GET", f"/quant/datasets/v2/{first_dataset.dataset_id}/preview?max_points=240"
        )
        first_preview = QuantMarketDatasetV2PreviewResponse.model_validate(first_preview_response)
        self.assertEqual(first_preview.total_bar_count, 365)
        self.assertEqual(first_preview.dataset.record_digest, first_dataset.record_digest)


if __name__ == "__main__":
    unittest.main()
