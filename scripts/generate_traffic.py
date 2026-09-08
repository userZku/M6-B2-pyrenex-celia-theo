"""Generate valid scoring traffic for the local Pyrenex stack.

Example:
    python scripts/generate_traffic.py --requests 500 --concurrency 20
"""
from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class Result:
    status: int | None
    elapsed: float
    error: str | None = None


def build_payload(randomizer: random.Random) -> dict[str, object]:
    """Build a valid loan payload with enough variation for live dashboards."""
    return {
        "loan_amnt": randomizer.choice([5000, 7500, 10000, 15000, 25000]),
        "int_rate": round(randomizer.uniform(6.0, 24.0), 2),
        "installment": round(randomizer.uniform(150.0, 700.0), 2),
        "annual_inc": randomizer.choice([35000, 45000, 55000, 75000, 120000]),
        "dti": round(randomizer.uniform(2.0, 38.0), 2),
        "delinq_2yrs": randomizer.randint(0, 3),
        "fico_range_low": randomizer.randint(650, 780),
        "revol_util": round(randomizer.uniform(10.0, 95.0), 1),
        "term": randomizer.choice(["36 months", "60 months"]),
        "grade": randomizer.choice(["A", "B", "C", "D", "E"]),
        "home_ownership": randomizer.choice(["RENT", "OWN", "MORTGAGE"]),
        "verification_status": randomizer.choice(
            ["Verified", "Source Verified", "Not Verified"]
        ),
        "purpose": randomizer.choice(
            ["debt_consolidation", "credit_card", "home_improvement"]
        ),
        "emp_length": randomizer.choice(
            ["< 1 year", "2 years", "5 years", "10+ years"]
        ),
    }


def send_request(url: str, payload: dict[str, object], timeout: float) -> Result:
    started = time.perf_counter()
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            return Result(response.status, time.perf_counter() - started)
    except HTTPError as error:
        return Result(error.code, time.perf_counter() - started, str(error))
    except (URLError, TimeoutError, OSError) as error:
        return Result(None, time.perf_counter() - started, str(error))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://localhost:8001/score",
        help="Scoring endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=100,
        help="Number of requests to send (default: %(default)s)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Maximum simultaneous requests (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for reproducible payload generation",
    )
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.timeout <= 0:
        parser.error("--requests, --concurrency and --timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    randomizer = random.Random(args.seed)
    payloads = [build_payload(randomizer) for _ in range(args.requests)]
    started = time.perf_counter()
    results: list[Result] = []

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(send_request, args.url, payload, args.timeout)
            for payload in payloads
        ]
        for future in as_completed(futures):
            results.append(future.result())

    elapsed = time.perf_counter() - started
    successful = sum(result.status is not None and 200 <= result.status < 300 for result in results)
    errors = len(results) - successful
    average_latency = sum(result.elapsed for result in results) / len(results)
    print(f"Sent: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Errors: {errors}")
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"Throughput: {len(results) / elapsed:.2f} req/s")
    print(f"Average latency: {average_latency * 1000:.1f} ms")
    if errors:
        for result in results:
            if result.error:
                print(f"Error: status={result.status} detail={result.error}")
                break
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
