import pandas as pd
from app.service.account_statement_service import reconcile_bank_and_upi
from app.service.upi_statement_service import UPIStatementService


def test_extract_transactions_uses_actual_upi_columns(tmp_path):
    file_path = tmp_path / "upi.csv"
    pd.DataFrame([
        {
            "Payer/Receiver": "Hari Customer 016",
            "Paid via": "Google Pay",
            "Type": "Credit",
            "Creation time": "2026-05-01 10:15:22",
            "Transaction ID": "T260501847291",
            "Amount": "2950",
            "Status": "Settled",
            "Notes": "Customer payment",
        }
    ]).to_csv(file_path, index=False)

    result = UPIStatementService.extract_transactions(str(file_path))

    assert result["success"] is True
    assert result["transactions"][0]["date"] == "2026-05-01 10:15:22"
    assert result["transactions"][0]["description"] == "Hari Customer 016"
    assert result["transactions"][0]["upi_id"] == "Google Pay"
    assert result["transactions"][0]["transaction_id"] == "T260501847291"
    assert result["transactions"][0]["amount"] == 2950.0
    assert result["transactions"][0]["type"] == "Credit"
    assert result["transactions"][0]["status"] == "Settled"
    assert result["transactions"][0]["notes"] == "Customer payment"


def test_reconcile_bank_and_upi_reports_non_upi_bank_and_accounting_upi_exception():
    bank_transactions = [
        {"date": "2026-05-01", "description": "Hari Customer 016", "debit": 0, "credit": 2950},
        {"date": "2026-05-02", "description": "Bank Transfer", "debit": 1000, "credit": 0},
    ]
    upi_transactions = [
        {"date": "2026-05-01 10:15:22", "description": "Hari Customer 016", "upi_id": "Google Pay", "transaction_id": "T1", "amount": 2950, "type": "Credit", "status": "Settled"},
    ]
    accounting_data = [
        {"type": "expense", "expense": 1761, "date": "2026-05-03", "ref_no": "EXP-1", "description": "Electricity Bill"},
    ]

    result = reconcile_bank_and_upi(bank_transactions, upi_transactions, accounting_data)

    assert result["matched_count"] == 1
    assert result["unmatched_upi_count"] == 1
    assert result["non_upi_bank_transactions"] == 1
    assert result["upi_missing_in_bank"][0]["source"] == "accounting_upi"
    assert result["upi_missing_in_bank"][0]["reason"] == "Present in accounting and UPI but missing in bank statement"
