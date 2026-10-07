"""
telebirr_verify.py

Prototype: verify a Telebirr transaction by looking up its public receipt
page and parsing out the transaction details.

HOW IT WORKS
------------
Every Telebirr transaction has a public receipt at:

    https://transactioninfo.ethiotelecom.et/receipt/{receipt_no}

`receipt_no` is the transaction number sent to you via SMS when you
receive a payment (also shown in the Telebirr app's transaction history).
This script fetches that page and extracts the fields we care about:
sender name, amount, receiver, date, and status.

IMPORTANT - READ BEFORE RUNNING
--------------------------------
1. NETWORK / HOSTING: Ethio Telecom blocks this endpoint for requests
   coming from foreign IP addresses. This script will likely fail (timeout
   or connection error) if you run it from outside Ethiopia (including most
   cloud VPS providers). To actually test this, you need to run it from:
     - A server/VPS physically hosted in Ethiopia, OR
     - Your own machine on an Ethiopian ISP connection, OR
     - Behind an Ethiopia-based proxy
   This sandbox has no network access at all, so this code has NOT been
   tested against the live site yet - see "WHAT'S UNVERIFIED" below.

2. FRAGILE BY DESIGN: This relies on parsing a public HTML page that
   Ethio Telecom did not design as an API. The page structure can change
   at any time without notice, silently breaking the parser. The code
   below is defensive (tries multiple strategies, never guesses), but you
   MUST test it against real receipt numbers before trusting it in
   production, and should monitor for silent parsing failures.

3. WHAT'S UNVERIFIED: The exact HTML field names/structure below are my
   best-effort guess based on how these receipt pages are typically built
   (label/value pairs in a table or dl/dt list) and how similar open-source
   parsers approach it. You will need to:
     a. Fetch one real receipt page's HTML (save it to a file)
     b. Look at the actual structure
     c. Adjust the CSS selectors in `_extract_fields()` accordingly
   I've written this so that step (c) is a small, isolated change.

USAGE
-----
    from telebirr_verify import verify_telebirr

    result = verify_telebirr("CE12345678AB")  # example receipt number
    if result.success:
        print(result.sender_name, result.amount, result.status)
    else:
        print("Verification failed:", result.error)
"""

from dataclasses import dataclass
from typing import Optional
import re

import requests
from bs4 import BeautifulSoup

RECEIPT_URL_TEMPLATE = "https://transactioninfo.ethiotelecom.et/receipt/{receipt_no}"

# Keep this generous but not infinite - a hung request shouldn't hang your checkout flow.
REQUEST_TIMEOUT_SECONDS = 10

# A normal browser User-Agent tends to be treated more kindly than the
# default python-requests one. Adjust freely.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


@dataclass
class TelebirrVerificationResult:
    success: bool
    receipt_no: str
    sender_name: Optional[str] = None
    receiver_name: Optional[str] = None
    amount: Optional[float] = None
    transaction_date: Optional[str] = None
    status: Optional[str] = None
    raw_fields: Optional[dict] = None   # everything we managed to parse, unfiltered
    error: Optional[str] = None


class TelebirrFetchError(Exception):
    """Raised when we can't even reach/load the receipt page."""


def _fetch_receipt_html(receipt_no: str) -> str:
    """
    Fetch the raw HTML of the public receipt page for a given receipt number.

    Raises TelebirrFetchError on network failure, timeout, or non-200 response.
    This is the piece most likely to fail from outside Ethiopia - see module
    docstring.
    """
    url = RECEIPT_URL_TEMPLATE.format(receipt_no=receipt_no)
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        raise TelebirrFetchError(
            f"Could not reach Telebirr receipt page (likely a network/hosting "
            f"issue - see module docstring about foreign-IP blocking): {exc}"
        ) from exc

    if resp.status_code != 200:
        raise TelebirrFetchError(
            f"Receipt page returned HTTP {resp.status_code} for receipt_no={receipt_no!r}. "
            f"This usually means the receipt number is invalid/expired, or the "
            f"page structure/URL has changed."
        )

    return resp.text


def _clean(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    text = text.strip()
    return text or None


def _parse_amount(text: Optional[str]) -> Optional[float]:
    """
    Pull a numeric amount out of strings like 'ETB 450.00' or '450.00 Birr'.
    Returns None if nothing parseable is found - never guesses.
    """
    if not text:
        return None
    match = re.search(r"[\d,]+\.?\d*", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _extract_fields(html: str) -> dict:
    """
    Parse the receipt HTML into a flat dict of {label: value}.

    UNVERIFIED / NEEDS REAL-WORLD TESTING (see module docstring, point 3):
    This assumes the page renders the receipt as label/value pairs, which is
    the near-universal pattern for these kinds of receipt pages (a table,
    or repeated <dt>/<dd> or <div> pairs). Two common structures are tried
    below. If neither matches, we return an empty dict and let the caller
    surface a clear "couldn't parse" error rather than silently returning
    wrong data.
    """
    soup = BeautifulSoup(html, "html.parser")
    fields = {}

    # Strategy 1: HTML table with two columns (label | value) - very common
    # for government/telecom receipt pages.
    for row in soup.select("table tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) == 2:
            label = _clean(cells[0].get_text())
            value = _clean(cells[1].get_text())
            if label and value:
                fields[label] = value

    # Strategy 2: definition list <dt>/<dd> pairs.
    if not fields:
        dts = soup.select("dt")
        dds = soup.select("dd")
        if dts and len(dts) == len(dds):
            for dt, dd in zip(dts, dds):
                label = _clean(dt.get_text())
                value = _clean(dd.get_text())
                if label and value:
                    fields[label] = value

    # Strategy 3: fallback - look for common "label: value" text patterns
    # anywhere on the page (last resort, noisier).
    if not fields:
        text_blocks = soup.get_text("\n").split("\n")
        for line in text_blocks:
            if ":" in line:
                label, _, value = line.partition(":")
                label, value = _clean(label), _clean(value)
                if label and value and len(label) < 40:
                    fields[label] = value

    return fields


def _match_field(fields: dict, *candidate_labels: str) -> Optional[str]:
    """
    Look up a value by trying several possible label spellings
    (case-insensitive, partial match), since we don't yet know the exact
    labels the real page uses (English vs Amharic, exact wording, etc.).
    """
    lowered = {k.lower(): v for k, v in fields.items()}
    for candidate in candidate_labels:
        candidate_l = candidate.lower()
        for key, value in lowered.items():
            if candidate_l in key:
                return value
    return None


def verify_telebirr(receipt_no: str) -> TelebirrVerificationResult:
    """
    Main entry point. Fetches and parses a Telebirr receipt.

    Never raises for "normal" failure modes (bad receipt number, page
    unreachable, parsing failure) - those come back as
    `TelebirrVerificationResult(success=False, error=...)` so calling code
    (e.g. a shopkeeper-facing screen) can show a clean message instead of
    crashing.
    """
    receipt_no = receipt_no.strip()
    if not receipt_no:
        return TelebirrVerificationResult(
            success=False, receipt_no=receipt_no, error="Empty receipt number."
        )

    try:
        html = _fetch_receipt_html(receipt_no)
    except TelebirrFetchError as exc:
        return TelebirrVerificationResult(success=False, receipt_no=receipt_no, error=str(exc))

    fields = _extract_fields(html)
    if not fields:
        return TelebirrVerificationResult(
            success=False,
            receipt_no=receipt_no,
            error=(
                "Fetched the page but couldn't parse any fields from it. "
                "The page structure has likely changed - inspect the raw "
                "HTML and update _extract_fields()."
            ),
        )

    sender_name = _match_field(fields, "payer", "sender", "from", "customer name")
    receiver_name = _match_field(fields, "credited party", "receiver", "receiver name", "merchant")
    amount_raw = _match_field(fields, "amount", "total amount", "paid amount")
    date_raw = _match_field(fields, "date", "transaction date", "payment date")
    status_raw = _match_field(fields, "status", "transaction status")

    return TelebirrVerificationResult(
        success=True,
        receipt_no=receipt_no,
        sender_name=sender_name,
        receiver_name=receiver_name,
        amount=_parse_amount(amount_raw),
        transaction_date=date_raw,
        status=status_raw,
        raw_fields=fields,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python telebirr_verify.py <receipt_no>")
        sys.exit(1)

    result = verify_telebirr(sys.argv[1])
    if result.success:
        print(f"Sender:   {result.sender_name}")
        print(f"Receiver: {result.receiver_name}")
        print(f"Amount:   {result.amount}")
        print(f"Date:     {result.transaction_date}")
        print(f"Status:   {result.status}")
        print(f"\nAll parsed fields (for debugging/verifying selectors):")
        for k, v in (result.raw_fields or {}).items():
            print(f"  {k!r}: {v!r}")
    else:
        print(f"FAILED: {result.error}")
