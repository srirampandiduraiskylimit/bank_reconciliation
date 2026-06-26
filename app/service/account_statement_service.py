import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except Exception:
        return 0.0


def normalize_date(date_value: Any) -> str:
    if not date_value:
        return ""

    date_value = str(date_value).strip()

    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y",
        "%d-%b-%Y",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_value, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue

    return date_value


def _normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _detect_payment_mode(text: str, fallback: Optional[str] = None) -> str:
    if fallback:
        return fallback

    lowered = text.lower()
    if any(keyword in lowered for keyword in ["upi", "gpay", "google pay", "phonepe", "paytm", "bharatpe"]):
        return "UPI"
    if any(keyword in lowered for keyword in ["neft", "rtgs", "imps", "bank transfer", "transfer"]):
        return "Bank Transfer"
    if "cash" in lowered:
        return "Cash"
    if any(keyword in lowered for keyword in ["cheque", "check"]):
        return "Cheque"
    return ""


def _normalize_accounting_entry(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not item:
        return {
            "date": "",
            "type": "",
            "ref_no": "",
            "particular": "",
            "party_customer_vendor": "",
            "category": "",
            "income": 0,
            "expense": 0,
            "loan_capital": 0,
            "payment_mode": "",
            "balance": 0,
        }

    item_type = str(item.get("type", "") or "").strip().lower()
    if item_type == "invoice":
        income_amount = safe_float(item.get("income"))
        expense_amount = 0.0
        capital_amount = 0.0
    elif item_type == "expense":
        income_amount = 0.0
        expense_amount = safe_float(item.get("expense"))
        capital_amount = 0.0
    elif item_type == "capital":
        income_amount = 0.0
        expense_amount = 0.0
        capital_amount = safe_float(item.get("loan_capital") or item.get("capital") or item.get("amount"))
    else:
        income_amount = safe_float(item.get("income"))
        expense_amount = safe_float(item.get("expense"))
        capital_amount = safe_float(item.get("loan_capital") or item.get("capital") or item.get("amount"))

    raw_text = " ".join([
        str(item.get("description", "") or ""),
        str(item.get("particular", "") or ""),
        str(item.get("particulars", "") or ""),
        str(item.get("party_customer_vendor", "") or ""),
        str(item.get("party", "") or ""),
        str(item.get("vendor", "") or ""),
        str(item.get("customer", "") or ""),
        str(item.get("ref_no", "") or ""),
    ])

    return {
        "date": normalize_date(item.get("date")),
        "type": item_type,
        "ref_no": str(item.get("ref_no", "") or ""),
        "particular": str(item.get("description", "") or "") or str(item.get("particular", "") or ""),
        "party_customer_vendor": str(item.get("party_customer_vendor", "") or item.get("party", "") or item.get("vendor", "") or item.get("customer", "") or ""),
        "category": str(item.get("category", "") or ""),
        "income": income_amount,
        "expense": expense_amount,
        "loan_capital": capital_amount,
        "payment_mode": _detect_payment_mode(raw_text, str(item.get("payment_mode", "") or item.get("mode", "") or "")),
        "balance": safe_float(item.get("balance")),
    }


def _is_transaction_type_match(bank_tx: Dict[str, Any], upi_tx: Dict[str, Any]) -> bool:
    bank_debit = safe_float(bank_tx.get("debit", 0)) > 0
    bank_credit = safe_float(bank_tx.get("credit", 0)) > 0
    upi_type = str(upi_tx.get("type", "")).strip().lower()

    if not upi_type:
        return True

    debit_keywords = {"debit", "dr", "paid", "withdrawal", "payment", "outgoing"}
    credit_keywords = {"credit", "cr", "received", "settled", "incoming", "refund"}

    if bank_credit and any(keyword in upi_type for keyword in credit_keywords):
        return True

    if bank_debit and any(keyword in upi_type for keyword in debit_keywords):
        return True

    return False


def _description_similarity(bank_description: str, upi_description: str, bank_party: str = "", upi_party: str = "", bank_ref: str = "", upi_ref: str = "") -> float:
    if not any([bank_description, upi_description, bank_party, upi_party, bank_ref, upi_ref]):
        return 0.0

    bank_text = _normalize_text(f"{bank_description} {bank_party} {bank_ref}")
    upi_text = _normalize_text(f"{upi_description} {upi_party} {upi_ref}")

    if not bank_text or not upi_text:
        return 0.0

    if bank_text == upi_text:
        return 1.0

    bank_tokens = set(bank_text.split())
    upi_tokens = set(upi_text.split())
    shared = bank_tokens & upi_tokens

    if not shared:
        if bank_text in upi_text or upi_text in bank_text:
            return 0.8
        return 0.0

    overlap_ratio = len(shared) / min(len(bank_tokens), len(upi_tokens))
    score = min(1.0, 0.5 + (overlap_ratio * 0.5))

    if bank_ref and upi_ref and bank_ref == upi_ref:
        score = max(score, 0.9)
    if bank_party and upi_party and _normalize_text(bank_party) == _normalize_text(upi_party):
        score = max(score, 0.9)

    return round(score, 2)


def _looks_like_upi_transaction(bank_tx: Dict[str, Any]) -> bool:
    description = str(bank_tx.get("description", "") or "").lower()
    reference = str(bank_tx.get("reference", "") or "").lower()
    tx_type = str(bank_tx.get("type", "") or "").lower()
    text = f"{description} {reference} {tx_type}"

    return any(keyword in text for keyword in ["upi", "google pay", "phonepe", "paytm", "gpay", "bharatpe"])


def _find_accounting_match(upi_tx: Dict[str, Any], accounting_data: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if not accounting_data:
        return None

    upi_amount = safe_float(upi_tx.get("amount", 0))
    upi_date = normalize_date(upi_tx.get("date"))
    upi_description = _normalize_text(upi_tx.get("description", ""))
    upi_party = _normalize_text(upi_tx.get("party_customer_vendor") or upi_tx.get("upi_id") or "")
    upi_ref = str(upi_tx.get("transaction_id", "") or "")

    best_match: Optional[Dict[str, Any]] = None
    best_score = 0.0

    for item in accounting_data:
        normalized_item = _normalize_accounting_entry(item)
        item_type = normalized_item["type"]
        if item_type not in {"invoice", "expense", "capital"}:
            continue

        amount = normalized_item["income"] or normalized_item["expense"] or normalized_item["loan_capital"]
        if round(amount, 2) != round(upi_amount, 2):
            continue

        item_date = normalized_item["date"]
        date_match = bool(not upi_date or not item_date or upi_date == item_date)
        if not date_match:
            continue

        ref_no = str(normalized_item.get("ref_no", "") or "")
        party = normalized_item.get("party_customer_vendor", "")
        description = normalized_item.get("particular", "")

        score = 0.0
        if ref_no and upi_ref and ref_no.lower() == upi_ref.lower():
            score = max(score, 0.95)
        if party and upi_party and _normalize_text(party) == upi_party:
            score = max(score, 0.9)

        desc_score = _description_similarity(upi_description, _normalize_text(description), upi_party, _normalize_text(party), upi_ref, ref_no)
        score = max(score, desc_score)

        if score >= best_score:
            best_score = score
            best_match = item

    if best_match is not None:
        return best_match

    return None


def reconcile_bank_and_upi(bank_transactions: List[Dict[str, Any]], upi_transactions: List[Dict[str, Any]], accounting_data: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Compare bank statement transactions with UPI statement transactions.
    Returns matched items, non-UPI bank transactions, UPI exceptions, and remarks.
    """
    matched: List[Dict[str, Any]] = []
    upi_missing_in_bank: List[Dict[str, Any]] = []
    bank_non_upi_transactions: List[Dict[str, Any]] = []
    bank_upi_transactions_without_match: List[Dict[str, Any]] = []
    used_upi_indexes: set[int] = set()

    for bank_tx in bank_transactions:
        bank_date = normalize_date(bank_tx.get("date"))
        bank_amount = 0.0
        if safe_float(bank_tx.get("debit", 0)) > 0:
            bank_amount = safe_float(bank_tx.get("debit", 0))
        elif safe_float(bank_tx.get("credit", 0)) > 0:
            bank_amount = safe_float(bank_tx.get("credit", 0))

        if bank_amount <= 0:
            continue

        matched_upi: Optional[Dict[str, Any]] = None
        matched_upi_idx: Optional[int] = None
        bank_description = _normalize_text(bank_tx.get("description", ""))
        bank_party = _normalize_text(bank_tx.get("party_customer_vendor") or bank_tx.get("party") or bank_tx.get("vendor") or bank_tx.get("customer") or "")
        bank_ref = str(bank_tx.get("reference", "") or "")

        for idx, upi_tx in enumerate(upi_transactions):
            if idx in used_upi_indexes:
                continue

            upi_amount = safe_float(upi_tx.get("amount", 0))
            upi_date = normalize_date(upi_tx.get("date"))
            upi_description = _normalize_text(upi_tx.get("description", ""))
            upi_party = _normalize_text(upi_tx.get("party_customer_vendor") or upi_tx.get("upi_id") or "")
            upi_ref = str(upi_tx.get("transaction_id", "") or "")

            if upi_amount <= 0 or bank_amount <= 0:
                continue

            amount_match = round(upi_amount, 2) == round(bank_amount, 2)
            if not amount_match:
                continue

            if bank_date and upi_date:
                date_match = bank_date == upi_date
            else:
                date_match = True

            if not date_match:
                continue

            if not _is_transaction_type_match(bank_tx, upi_tx):
                continue

            description_score = _description_similarity(bank_description, upi_description, bank_party, upi_party, bank_ref, upi_ref)
            if description_score < 0.3 and not (bank_description and upi_description):
                pass

            matched_upi = upi_tx
            matched_upi_idx = idx
            break

        if matched_upi is not None and matched_upi_idx is not None:
            used_upi_indexes.add(matched_upi_idx)
            matched.append({
                "source": "bank",
                "date": bank_date,
                "description": bank_tx.get("description", ""),
                "party_customer_vendor": bank_tx.get("party_customer_vendor") or bank_tx.get("party") or bank_tx.get("vendor") or bank_tx.get("customer") or "",
                "amount": bank_amount,
                "matched_with_upi": True,
                "upi_reference": matched_upi.get("transaction_id") or matched_upi.get("upi_id") or "",
                "remarks": "Matched with UPI transaction"
            })
        else:
            non_upi_entry = {
                "source": "bank",
                "date": bank_date,
                "description": bank_tx.get("description", ""),
                "party_customer_vendor": bank_tx.get("party_customer_vendor") or bank_tx.get("party") or bank_tx.get("vendor") or bank_tx.get("customer") or "",
                "amount": bank_amount,
                "matched_with_upi": False,
                "remarks": "No matching UPI transaction found; treated as a non-UPI bank transaction"
            }
            bank_non_upi_transactions.append(non_upi_entry)
            if _looks_like_upi_transaction(bank_tx):
                bank_upi_transactions_without_match.append(non_upi_entry)

    for idx, upi_tx in enumerate(upi_transactions):
        if idx in used_upi_indexes:
            continue

        upi_amount = safe_float(upi_tx.get("amount", 0))
        if upi_amount <= 0:
            continue

        accounting_match = _find_accounting_match(upi_tx, accounting_data) if accounting_data else None
        if accounting_match:
            upi_missing_in_bank.append({
                "source": "accounting_upi",
                "date": normalize_date(upi_tx.get("date")),
                "description": upi_tx.get("description", ""),
                "party_customer_vendor": upi_tx.get("party_customer_vendor") or upi_tx.get("upi_id") or "",
                "amount": upi_amount,
                "matched_with_upi": False,
                "accounting_entry": _normalize_accounting_entry(accounting_match),
                "reason": "Present in accounting and UPI but missing in bank statement"
            })
        else:
            upi_missing_in_bank.append({
                "source": "upi",
                "date": normalize_date(upi_tx.get("date")),
                "description": upi_tx.get("description", ""),
                "party_customer_vendor": upi_tx.get("party_customer_vendor") or upi_tx.get("upi_id") or "",
                "amount": upi_amount,
                "matched_with_upi": False,
                "reason": "No matching bank statement entry found"
            })

    remarks: List[str] = []
    if not bank_transactions:
        remarks.append("No bank transactions were parsed from the provided bank statement.")
    if not upi_transactions:
        remarks.append("No UPI transactions were parsed from the provided UPI statement.")

    if matched:
        remarks.append(f"{len(matched)} bank/UPI transaction(s) were matched.")
    if upi_missing_in_bank:
        remarks.append(f"{len(upi_missing_in_bank)} UPI transaction(s) are missing from the bank statement.")
    if bank_non_upi_transactions:
        remarks.append(f"{len(bank_non_upi_transactions)} bank transaction(s) were treated as non-UPI transactions.")
    if not matched and not upi_missing_in_bank and not bank_non_upi_transactions:
        remarks.append("Bank and UPI statements are fully aligned for the parsed data.")

    return {
        "matched_count": len(matched),
        "unmatched_count": len(upi_missing_in_bank) + len(bank_non_upi_transactions),
        "unmatched_upi_count": len(upi_missing_in_bank),
        "non_upi_bank_transactions": len(bank_non_upi_transactions),
        "matched_items": matched,
        "upi_missing_in_bank": upi_missing_in_bank,
        "bank_non_upi_transactions": bank_non_upi_transactions,
        "bank_upi_transactions_without_match": bank_upi_transactions_without_match,
        "missing_count": len(upi_missing_in_bank),
        "missing_data": upi_missing_in_bank,
        "remarks": remarks,
        "statistics": {
            "matched_count": len(matched),
            "unmatched_count": len(upi_missing_in_bank) + len(bank_non_upi_transactions),
        },
    }


def _extract_accounting_id(item: Dict[str, Any], item_type: str) -> Optional[Any]:
    if not item:
        return None

    if item_type == "invoice":
        return item.get("invoice_id") or item.get("id") or item.get("_id")
    if item_type == "expense":
        return item.get("expense_id") or item.get("id") or item.get("_id")
    if item_type == "capital":
        return item.get("capital_id") or item.get("id") or item.get("_id")
    return item.get("id") or item.get("_id")


def reconcile_transactions(bank_transactions, accounts_data):
    """
    Reconcile bank transactions with accounting records.
    
    Args:
        bank_transactions: List of bank statement transactions
        accounts_data: List of accounting entries (invoices, expenses, capital)
    
    Returns:
        List of reconciliation results
    """
    result = []

    # Create lookups for accounting entries by date+amount and amount-only for fallback matching
    account_lookup = {}
    amount_lookup = {}
    used_accounting_indices = set()
    
    for idx, item in enumerate(accounts_data):
        item_date = normalize_date(item.get("date"))
        item_ref = str(item.get("ref_no", "")).strip()
        item_type = str(item.get("type", "")).strip().lower()
        
        # Determine the amount based on type
        if item_type == "invoice":
            amount = safe_float(item.get("income"))
        elif item_type == "expense":
            amount = safe_float(item.get("expense"))
        elif item_type == "capital":
            amount = safe_float(
                item.get("loan_capital") or 
                item.get("capital") or 
                item.get("amount")
            )
        else:
            continue  # Skip unknown types
            
        # Create key for lookup
        key = f"{item_date}_{amount:.2f}"
        if key not in account_lookup:
            account_lookup[key] = []
        
        account_lookup[key].append({
            "ref_no": item_ref,
            "type": item_type,
            "amount": amount,
            "date": item_date,
            "original": item,
            "index": idx
        })

        amount_key = f"{amount:.2f}"
        if amount_key not in amount_lookup:
            amount_lookup[amount_key] = []

        amount_lookup[amount_key].append({
            "ref_no": item_ref,
            "type": item_type,
            "amount": amount,
            "date": item_date,
            "original": item,
            "index": idx
        })

    # Process each bank transaction
    for tx in bank_transactions:
        tx_date = normalize_date(tx.get("date"))
        debit = safe_float(tx.get("debit", 0))
        credit = safe_float(tx.get("credit", 0))
        
        amount = 0
        is_debit = False
        is_credit = False
        
        if debit > 0:
            amount = debit
            is_debit = True
        elif credit > 0:
            amount = credit
            is_credit = True
        else:
            # Skip zero amount transactions
            result.append({
                "date": tx_date,
                "description": tx.get("description", ""),
                "amount": 0,
                "matched": False,
                "match_type": None,
                "matched_ref_no": None,
                "add_invoice": False,
                "add_expense": False,
                "add_capital": False,
                "capital_id": None,
                "invoice_id": None,
                "expense_id": None,
                "missing_transaction": True,
                "action": "missing_transaction",
                "reason": "Zero amount transaction - skipped"
            })
            continue

        matched = False
        match_type = None
        matched_ref = None
        matched_item = None
        matched_ids = {
            "capital_id": None,
            "invoice_id": None,
            "expense_id": None,
        }

        # Look for matching accounting entry by date and amount, with amount-only fallback
        lookup_key = f"{tx_date}_{amount:.2f}"
        candidates = []
        
        if lookup_key in account_lookup:
            candidates = account_lookup[lookup_key]
        else:
            amount_key = f"{amount:.2f}"
            candidates = amount_lookup.get(amount_key, [])
        
        if candidates:
            # Find the best match based on transaction type and avoid reusing the same accounting record
            for candidate in candidates:
                candidate_type = candidate["type"]
                candidate_idx = candidate["index"]
                if candidate_idx in used_accounting_indices:
                    continue
                
                # For credit transactions, match with invoices or capital
                if is_credit and candidate_type in ["invoice", "capital"]:
                    matched = True
                    match_type = candidate_type
                    matched_ref = candidate["ref_no"]
                    matched_item = candidate["original"]
                    if candidate_type == "invoice":
                        matched_ids["invoice_id"] = _extract_accounting_id(matched_item, candidate_type)
                    elif candidate_type == "expense":
                        matched_ids["expense_id"] = _extract_accounting_id(matched_item, candidate_type)
                    elif candidate_type == "capital":
                        matched_ids["capital_id"] = _extract_accounting_id(matched_item, candidate_type)
                    used_accounting_indices.add(candidate_idx)
                    break
                
                # For debit transactions, match with expenses
                elif is_debit and candidate_type == "expense":
                    matched = True
                    match_type = "expense"
                    matched_ref = candidate["ref_no"]
                    matched_item = candidate["original"]
                    matched_ids["expense_id"] = _extract_accounting_id(matched_item, candidate_type)
                    used_accounting_indices.add(candidate_idx)
                    break

        # Create result entry
        result_entry = {
            "date": tx_date,
            "description": tx.get("description", ""),
            "amount": amount,
            "matched": matched,
            "match_type": match_type,
            "matched_ref_no": matched_ref,
            "add_invoice": False,
            "add_expense": False,
            "add_capital": False,
            "capital_id": matched_ids["capital_id"],
            "invoice_id": matched_ids["invoice_id"],
            "expense_id": matched_ids["expense_id"],
            "missing_transaction": not matched,
            "action": "matched" if matched else "missing_transaction",
            "reason": f"Matched with {match_type.title()} {matched_ref}" if matched and match_type else "No matching accounting entry found"
        }

        # Suggest action for unmatched transactions
        if not matched:
            if is_credit:
                result_entry["add_invoice"] = True
                result_entry["action"] = "add_invoice"
                result_entry["reason"] = f"Unmatched credit of {amount} - consider adding invoice"
            elif is_debit:
                result_entry["add_expense"] = True
                result_entry["action"] = "add_expense"
                result_entry["reason"] = f"Unmatched debit of {amount} - consider adding expense"

        result.append(result_entry)

    return result