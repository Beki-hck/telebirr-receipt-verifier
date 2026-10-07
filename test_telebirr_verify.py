"""
Sanity-check the parsing logic using a MOCK receipt page (table-based, the
most common structure for this kind of page), since this sandbox has no
network access to hit the real Ethio Telecom site.

This proves the parsing/extraction logic itself works correctly. It does
NOT prove the real page has this exact structure - that still needs to be
confirmed by fetching one real receipt from Ethiopia-hosted infrastructure
(see README.md).
"""

from unittest.mock import patch, Mock

from telebirr_verify import verify_telebirr

MOCK_RECEIPT_HTML = """
<html>
  <body>
    <table>
      <tr><td>Payer Name</td><td>Abebe Kebede</td></tr>
      <tr><td>Payer telebirr no.</td><td>2519*****123</td></tr>
      <tr><td>Receiver Name</td><td>Baltina Shop PLC</td></tr>
      <tr><td>Transaction Date</td><td>08-09-2026 14:32:10</td></tr>
      <tr><td>Total Paid Amount</td><td>ETB 450.00</td></tr>
      <tr><td>Transaction Status</td><td>Completed</td></tr>
    </table>
  </body>
</html>
"""


def test_parses_mock_receipt_correctly():
    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.text = MOCK_RECEIPT_HTML

    with patch("telebirr_verify.requests.get", return_value=fake_response):
        result = verify_telebirr("CE12345678AB")

    assert result.success, f"Expected success, got error: {result.error}"
    assert result.sender_name == "Abebe Kebede"
    assert result.receiver_name == "Baltina Shop PLC"
    assert result.amount == 450.00
    assert result.status == "Completed"
    print("PASS: mock receipt parsed correctly ->")
    print(f"  sender={result.sender_name!r} amount={result.amount!r} status={result.status!r}")


def test_handles_unreachable_page_cleanly():
    import requests

    with patch("telebirr_verify.requests.get", side_effect=requests.exceptions.ConnectTimeout("simulated timeout")):
        result = verify_telebirr("CE12345678AB")

    assert not result.success
    assert "network/hosting" in result.error or "Could not reach" in result.error
    print(f"PASS: unreachable page handled cleanly -> error={result.error!r}")


def test_handles_bad_receipt_number_cleanly():
    fake_response = Mock()
    fake_response.status_code = 404
    fake_response.text = "Not Found"

    with patch("telebirr_verify.requests.get", return_value=fake_response):
        result = verify_telebirr("INVALID")

    assert not result.success
    print(f"PASS: bad receipt number handled cleanly -> error={result.error!r}")


if __name__ == "__main__":
    test_parses_mock_receipt_correctly()
    test_handles_unreachable_page_cleanly()
    test_handles_bad_receipt_number_cleanly()
    print("\nAll tests passed.")
