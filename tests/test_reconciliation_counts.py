from app.service.account_statement_service import reconcile_transactions


def test_reconciliation_does_not_reuse_accounting_entries():
    bank_transactions = [
        {"date": "2026-05-01", "description": "Payment", "debit": 1000, "credit": 0},
        {"date": "2026-05-02", "description": "Receipt", "debit": 0, "credit": 1000},
    ]
    accounting_data = [
        {"type": "expense", "expense": 1000, "date": "2026-05-01", "ref_no": "EXP-1", "expense_id": 51},
        {"type": "invoice", "income": 1000, "date": "2026-05-02", "ref_no": "INV-1", "invoice_id": 77},
    ]

    reconciliation = reconcile_transactions(bank_transactions, accounting_data)

    assert reconciliation[0]["matched"] is True
    assert reconciliation[1]["matched"] is True
    assert reconciliation[0]["matched_ref_no"] == "EXP-1"
    assert reconciliation[1]["matched_ref_no"] == "INV-1"
    assert reconciliation[0]["action"] == "matched"
    assert reconciliation[0]["add_capital"] is False
    assert reconciliation[0]["missing_transaction"] is False
    assert reconciliation[0]["expense_id"] == 51
    assert reconciliation[1]["invoice_id"] == 77


def test_reconciliation_counts_follow_transaction_type():
    bank_transactions = [
        {"date": "2026-05-01", "description": "Expense", "debit": 1000, "credit": 0},
        {"date": "2026-05-02", "description": "Invoice", "debit": 0, "credit": 1000},
        {"date": "2026-05-03", "description": "Another expense", "debit": 500, "credit": 0},
    ]
    accounting_data = [
        {"type": "expense", "expense": 1000, "date": "2026-05-01", "ref_no": "EXP-1", "expense_id": 51},
        {"type": "invoice", "income": 1000, "date": "2026-05-02", "ref_no": "INV-1", "invoice_id": 77},
    ]

    reconciliation = reconcile_transactions(bank_transactions, accounting_data)

    assert sum(1 for item in reconciliation if item["matched"] is False) == 1
    assert sum(1 for item in reconciliation if item["add_expense"]) == 1
    assert sum(1 for item in reconciliation if item["add_invoice"]) == 0
    assert all(item["add_capital"] is False for item in reconciliation)
    assert reconciliation[-1]["action"] == "add_expense"
