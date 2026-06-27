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
    upi_description = _normalize_text(upi_tx.get("description", "") or upi_tx.get("notes", "") or "")
    upi_party = _normalize_text(upi_tx.get("party_customer_vendor") or upi_tx.get("upi_id") or "")
    upi_ref = str(upi_tx.get("transaction_id", "") or "")
    upi_notes = str(upi_tx.get("notes", "") or "")

    best_match: Optional[Dict[str, Any]] = None
    best_score = 0.0

    for item in accounting_data:
        normalized_item = _normalize_accounting_entry(item)
        item_type = normalized_item["type"]
        if item_type not in {"invoice", "expense", "capital"}:
            continue

        amount = normalized_item["income"] or normalized_item["expense"] or normalized_item["loan_capital"]
        if abs(amount - upi_amount) > 0.01:
            continue

        item_date = normalized_item["date"]
        date_match = bool(not upi_date or not item_date or upi_date == item_date)
        if not date_match:
            try:
                from datetime import datetime, timedelta
                upi_dt = datetime.strptime(upi_date, "%Y-%m-%d")
                item_dt = datetime.strptime(item_date, "%Y-%m-%d")
                if abs((upi_dt - item_dt).days) <= 1:
                    date_match = True
            except:
                pass
            if not date_match:
                continue

        ref_no = str(normalized_item.get("ref_no", "") or "")
        party = normalized_item.get("party_customer_vendor", "")
        description = normalized_item.get("particular", "")

        score = 0.0
        
        if ref_no:
            if ref_no.lower() in upi_notes.lower():
                score += 0.5
            if ref_no.lower() in upi_description.lower():
                score += 0.3
        
        if party and upi_party:
            if _normalize_text(party) == upi_party:
                score += 0.3
            elif _normalize_text(party) in upi_party or upi_party in _normalize_text(party):
                score += 0.2

        desc_score = _description_similarity(upi_description, _normalize_text(description), upi_party, _normalize_text(party), upi_ref, ref_no)
        score += desc_score * 0.3

        if score >= best_score and score >= 0.3:
            best_score = score
            best_match = item

    return best_match


def reconcile_bank_and_upi(bank_transactions: List[Dict[str, Any]], upi_transactions: List[Dict[str, Any]], accounting_data: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    matched: List[Dict[str, Any]] = []
    upi_missing_in_bank: List[Dict[str, Any]] = []
    bank_non_upi_transactions: List[Dict[str, Any]] = []
    bank_upi_transactions_without_match: List[Dict[str, Any]] = []
    used_upi_indexes: set[int] = set()
    
    accounting_lookup = {}
    if accounting_data:
        for item in accounting_data:
            ref_no = str(item.get("ref_no", "")).strip()
            if ref_no:
                accounting_lookup[ref_no] = {
                    "invoice_id": item.get("invoice_id"),
                    "expense_id": item.get("expense_id"),
                    "capital_id": item.get("capital_id"),
                    "type": str(item.get("type", "")).strip().lower(),
                    "particular": item.get("particular", ""),
                    "party_customer_vendor": item.get("party_customer_vendor", ""),
                    "payment_mode": item.get("payment_mode", ""),
                    "amount": safe_float(item.get("income") or item.get("expense") or item.get("loan_capital") or 0)
                }
    
    for bank_tx in bank_transactions:
        bank_date = normalize_date(bank_tx.get("date"))
        bank_amount = 0.0
        if safe_float(bank_tx.get("debit", 0)) > 0:
            bank_amount = safe_float(bank_tx.get("debit", 0))
            bank_type = "debit"
        elif safe_float(bank_tx.get("credit", 0)) > 0:
            bank_amount = safe_float(bank_tx.get("credit", 0))
            bank_type = "credit"
        else:
            continue

        if bank_amount <= 0:
            continue

        matched_upi: Optional[Dict[str, Any]] = None
        matched_upi_idx: Optional[int] = None
        best_match_score = 0.0
        best_match_reason = ""
        
        bank_description = _normalize_text(bank_tx.get("description", ""))
        bank_party = _normalize_text(bank_tx.get("party_customer_vendor") or bank_tx.get("party") or bank_tx.get("vendor") or bank_tx.get("customer") or "")
        bank_ref = str(bank_tx.get("reference", "") or "")

        for idx, upi_tx in enumerate(upi_transactions):
            if idx in used_upi_indexes:
                continue

            upi_amount = safe_float(upi_tx.get("amount", 0))
            upi_date = normalize_date(upi_tx.get("date"))
            upi_description = _normalize_text(upi_tx.get("description", "") or upi_tx.get("notes", "") or "")
            upi_party = _normalize_text(upi_tx.get("party_customer_vendor") or upi_tx.get("upi_id") or "")
            upi_ref = str(upi_tx.get("transaction_id", "") or "")
            upi_type = str(upi_tx.get("type", "")).strip().lower()
            upi_notes = str(upi_tx.get("notes", "") or "").lower()

            if upi_amount <= 0:
                continue

            if abs(upi_amount - bank_amount) > 0.01:
                continue

            date_match = False
            if bank_date and upi_date:
                from datetime import datetime, timedelta
                try:
                    bank_dt = datetime.strptime(bank_date, "%Y-%m-%d")
                    upi_dt = datetime.strptime(upi_date, "%Y-%m-%d")
                    date_diff = abs((bank_dt - upi_dt).days)
                    if date_diff <= 1:
                        date_match = True
                except:
                    if bank_date == upi_date:
                        date_match = True
            else:
                date_match = True

            if not date_match:
                continue

            type_match = False
            if bank_type == "debit" and ("debit" in upi_type or "dr" in upi_type):
                type_match = True
            elif bank_type == "credit" and ("credit" in upi_type or "cr" in upi_type):
                type_match = True
            
            if not type_match:
                continue

            score = 0.0
            match_reasons = []
            
            if bank_ref:
                bank_ref_lower = bank_ref.lower()
                if bank_ref_lower in upi_notes:
                    score += 0.6
                    match_reasons.append("Reference in notes")
                elif bank_ref_lower in upi_description:
                    score += 0.4
                    match_reasons.append("Reference in description")
            
            for acc_ref, acc_data in accounting_lookup.items():
                if acc_ref.lower() in upi_notes:
                    if abs(acc_data.get("amount", 0) - bank_amount) <= 0.01:
                        score += 0.5
                        match_reasons.append(f"Accounting reference {acc_ref} in notes")
                        accounting_ids = acc_data
                        break
            
            if bank_party and upi_party:
                if bank_party == upi_party:
                    score += 0.3
                    match_reasons.append("Party exact match")
                elif bank_party in upi_party or upi_party in bank_party:
                    score += 0.2
                    match_reasons.append("Party partial match")
            
            if bank_party and bank_party in upi_notes:
                score += 0.2
                match_reasons.append("Party in notes")
            
            if bank_description and upi_description:
                desc_score = _description_similarity(bank_description, upi_description, bank_party, upi_party, bank_ref, upi_ref)
                score += desc_score * 0.3
                if desc_score > 0.5:
                    match_reasons.append("Description match")

            if score > best_match_score and score >= 0.3:
                best_match_score = score
                matched_upi = upi_tx
                matched_upi_idx = idx
                best_match_reason = ", ".join(match_reasons) if match_reasons else "Amount and date match"

        if matched_upi is not None and matched_upi_idx is not None:
            used_upi_indexes.add(matched_upi_idx)
            
            accounting_ids = {}
            upi_notes = str(matched_upi.get("notes", "") or "").lower()
            for acc_ref, acc_data in accounting_lookup.items():
                if acc_ref.lower() in upi_notes:
                    if abs(acc_data.get("amount", 0) - bank_amount) <= 0.01:
                        accounting_ids = acc_data
                        break
            
            if not accounting_ids and bank_ref in accounting_lookup:
                accounting_ids = accounting_lookup[bank_ref]
            
            matched.append({
                "source": "bank",
                "date": bank_date,
                "description": bank_tx.get("description", ""),
                "party_customer_vendor": bank_tx.get("party_customer_vendor") or bank_tx.get("party") or bank_tx.get("vendor") or bank_tx.get("customer") or "",
                "amount": bank_amount,
                "matched_with_upi": True,
                "upi_reference": matched_upi.get("transaction_id") or matched_upi.get("upi_id") or "",
                "upi_party": matched_upi.get("description") or matched_upi.get("party_customer_vendor") or "",
                "match_score": round(best_match_score, 2),
                "match_reason": best_match_reason,
                "invoice_id": accounting_ids.get("invoice_id"),
                "expense_id": accounting_ids.get("expense_id"),
                "capital_id": accounting_ids.get("capital_id"),
                "status": "UPI Matched"
            })
        else:
            is_upi_like = _looks_like_upi_transaction(bank_tx)
            
            accounting_ids = {}
            if bank_ref in accounting_lookup:
                accounting_ids = accounting_lookup[bank_ref]
            
            non_upi_entry = {
                "source": "bank",
                "date": bank_date,
                "description": bank_tx.get("description", ""),
                "party_customer_vendor": bank_tx.get("party_customer_vendor") or bank_tx.get("party") or bank_tx.get("vendor") or bank_tx.get("customer") or "",
                "amount": bank_amount,
                "matched_with_upi": False,
                "invoice_id": accounting_ids.get("invoice_id"),
                "expense_id": accounting_ids.get("expense_id"),
                "capital_id": accounting_ids.get("capital_id"),
                "status": "Non-UPI Transaction",
                "remarks": "No matching UPI transaction found"
            }
            bank_non_upi_transactions.append(non_upi_entry)
            
            if is_upi_like:
                bank_upi_transactions_without_match.append(non_upi_entry)

    for idx, upi_tx in enumerate(upi_transactions):
        if idx in used_upi_indexes:
            continue

        upi_amount = safe_float(upi_tx.get("amount", 0))
        if upi_amount <= 0:
            continue

        accounting_match = _find_accounting_match(upi_tx, accounting_data) if accounting_data else None
        
        accounting_ids = {}
        if accounting_match:
            accounting_ids = {
                "invoice_id": accounting_match.get("invoice_id"),
                "expense_id": accounting_match.get("expense_id"),
                "capital_id": accounting_match.get("capital_id"),
                "ref_no": accounting_match.get("ref_no")
            }
        else:
            upi_notes = str(upi_tx.get("notes", "") or "")
            import re
            ref_match = re.search(r'(EXP-\d+|INV-\d+|CAP-\d+)', upi_notes)
            if ref_match and ref_match.group(1) in accounting_lookup:
                accounting_ids = accounting_lookup[ref_match.group(1)]
        
        upi_entry = {
            "source": "accounting_upi" if accounting_match else "upi",
            "date": normalize_date(upi_tx.get("date")),
            "description": upi_tx.get("description", "") or upi_tx.get("notes", ""),
            "party_customer_vendor": upi_tx.get("party_customer_vendor") or upi_tx.get("upi_id") or "",
            "amount": upi_amount,
            "matched_with_upi": False,
            "invoice_id": accounting_ids.get("invoice_id"),
            "expense_id": accounting_ids.get("expense_id"),
            "capital_id": accounting_ids.get("capital_id"),
            "status": "UPI Pending",
            "reason": "No matching bank statement entry found"
        }
        
        if accounting_match:
            upi_entry.update({
                "accounting_entry": _normalize_accounting_entry(accounting_match),
                "reason": "Present in accounting and UPI but missing in bank statement"
            })
            
        upi_missing_in_bank.append(upi_entry)

    remarks: List[str] = []
    if not bank_transactions:
        remarks.append("No bank transactions were parsed from the provided bank statement.")
    if not upi_transactions:
        remarks.append("No UPI transactions were parsed from the provided UPI statement.")

    if matched:
        remarks.append(f"{len(matched)} bank/UPI transactions were matched.")
    if upi_missing_in_bank:
        remarks.append(f"{len(upi_missing_in_bank)} UPI transactions are missing from the bank statement.")
    if bank_non_upi_transactions:
        remarks.append(f"{len(bank_non_upi_transactions)} bank transactions were treated as non-UPI transactions.")
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
        "remarks": remarks
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


def reconcile_transactions(bank_transactions, accounts_data, upi_transactions=None):
    """
    Reconcile bank transactions with accounting records and UPI transactions.
    
    Matching Logic:
    1. PRIMARY: Date + Amount must match
    2. SECONDARY: Transaction type (debit/credit) must match
    """
    result = []
    
    account_lookup = {}
    amount_lookup = {}
    used_accounting_indices = set()
    upi_amount_date_lookup = {}
    
    if upi_transactions:
        for upi_tx in upi_transactions:
            upi_amount = safe_float(upi_tx.get("amount", 0))
            upi_date = normalize_date(upi_tx.get("date"))
            upi_date_only = upi_date.split()[0] if upi_date else ""
            key = f"{upi_date_only}_{upi_amount:.2f}"
            if key not in upi_amount_date_lookup:
                upi_amount_date_lookup[key] = []
            upi_amount_date_lookup[key].append(upi_tx)
    
    all_accounting_entries = []
    
    for idx, item in enumerate(accounts_data):
        item_date = normalize_date(item.get("date"))
        item_ref = str(item.get("ref_no", "")).strip()
        item_type = str(item.get("type", "")).strip().lower()
        payment_mode = str(item.get("payment_mode", "")).strip().lower()
        
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
            continue
            
        key = f"{item_date}_{amount:.2f}"
        if key not in account_lookup:
            account_lookup[key] = []
        
        entry_data = {
            "ref_no": item_ref,
            "type": item_type,
            "amount": amount,
            "date": item_date,
            "payment_mode": payment_mode,
            "original": item,
            "index": idx,
            "ids": {
                "invoice_id": item.get("invoice_id"),
                "expense_id": item.get("expense_id"),
                "capital_id": item.get("capital_id")
            },
            "matched": False,
            "upi_matched": False,
            "bank_matched": False
        }
        
        account_lookup[key].append(entry_data)

        amount_key = f"{amount:.2f}"
        if amount_key not in amount_lookup:
            amount_lookup[amount_key] = []

        amount_lookup[amount_key].append(entry_data)
        all_accounting_entries.append(entry_data)
    
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

        lookup_key = f"{tx_date}_{amount:.2f}"
        candidates = []
        
        if lookup_key in account_lookup:
            candidates = account_lookup[lookup_key]
        else:
            amount_key = f"{amount:.2f}"
            candidates = amount_lookup.get(amount_key, [])
        
        if candidates:
            for candidate in candidates:
                candidate_type = candidate["type"]
                candidate_idx = candidate["index"]
                
                if candidate_idx in used_accounting_indices:
                    continue
                
                type_match = False
                if is_credit and candidate_type in ["invoice", "capital"]:
                    type_match = True
                elif is_debit and candidate_type == "expense":
                    type_match = True
                elif is_debit and candidate_type == "capital":
                    type_match = True
                
                if not type_match:
                    continue
                
                matched = True
                match_type = candidate_type
                matched_ref = candidate["ref_no"]
                matched_item = candidate["original"]
                matched_ids = candidate["ids"].copy()
                used_accounting_indices.add(candidate_idx)
                candidate["bank_matched"] = True
                candidate["matched"] = True
                break

        upi_match = None
        if upi_transactions:
            tx_date_only = tx_date.split()[0] if tx_date else ""
            upi_key = f"{tx_date_only}_{amount:.2f}"
            if upi_key in upi_amount_date_lookup:
                for upi_tx in upi_amount_date_lookup[upi_key]:
                    upi_type = str(upi_tx.get("type", "")).strip().lower()
                    if (is_debit and "debit" in upi_type) or (is_credit and "credit" in upi_type):
                        upi_match = upi_tx
                        break

        add_invoice = False
        add_expense = False
        add_capital = False
        action = "none"
        status = "Reconciled" if matched else "Pending Review"
        
        if not matched:
            if is_credit:
                add_invoice = True
                action = "add_invoice"
                status = "Pending Review"
            elif is_debit:
                add_expense = True
                action = "add_expense"
                status = "Pending Review"

        result_entry = {
            "date": tx_date,
            "description": tx.get("description", ""),
            "party_customer_vendor": tx.get("party_customer_vendor") or tx.get("party") or tx.get("vendor") or tx.get("customer") or "",
            "amount": amount,
            "type": "debit" if is_debit else "credit",
            "matched": matched,
            "match_type": match_type,
            "matched_ref_no": matched_ref,
            "add_invoice": add_invoice,
            "add_expense": add_expense,
            "add_capital": add_capital,
            "invoice_id": matched_ids.get("invoice_id"),
            "expense_id": matched_ids.get("expense_id"),
            "capital_id": matched_ids.get("capital_id"),
            "upi_matched": upi_match is not None,
            "upi_reference": upi_match.get("transaction_id") if upi_match else None,
            "status": status,
            "action": action,
            "action_label": "Add Expense" if add_expense else "Add Invoice" if add_invoice else "Add Capital" if add_capital else "None"
        }

        result.append(result_entry)

    matched_accounting = []
    unmatched_accounting = []
    
    for entry in all_accounting_entries:
        is_bank_matched = entry.get("bank_matched", False)
        
        upi_match = None
        if upi_transactions:
            entry_date_only = entry['date'].split()[0] if entry['date'] else ""
            upi_key = f"{entry_date_only}_{entry['amount']:.2f}"
            if upi_key in upi_amount_date_lookup:
                for upi_tx in upi_amount_date_lookup[upi_key]:
                    upi_type = str(upi_tx.get("type", "")).strip().lower()
                    entry_type = entry["type"]
                    if (entry_type in ["invoice", "capital"] and "credit" in upi_type) or \
                       (entry_type == "expense" and "debit" in upi_type):
                        upi_match = upi_tx
                        break
        
        payment_mode = entry.get("payment_mode", "").lower()
        is_cash = payment_mode == "cash"
        
        if is_bank_matched:
            action = "none"
            status = "Matched"
            remark = ""
        else:
            if is_cash:
                action = "remark"
                status = "Cash Transaction"
                remark = "Cash transaction - not reflected in bank statement"
            else:
                action = "add_to_bank"
                status = "Pending"
                remark = ""
        
        accounting_entry = {
            "date": entry["date"],
            "description": entry["original"].get("particular", ""),
            "party_customer_vendor": entry["original"].get("party_customer_vendor", ""),
            "amount": entry["amount"],
            "type": entry["type"],
            "ref_no": entry["ref_no"],
            "payment_mode": entry.get("payment_mode", ""),
            "matched": is_bank_matched,
            "status": status,
            "action": action,
            "action_label": "Cash - Not in Bank" if is_cash and not is_bank_matched else "Add to Bank" if not is_cash and not is_bank_matched else "None",
            "remark": remark,
            "invoice_id": entry["ids"].get("invoice_id"),
            "expense_id": entry["ids"].get("expense_id"),
            "capital_id": entry["ids"].get("capital_id"),
            "upi_matched": upi_match is not None,
            "upi_reference": upi_match.get("transaction_id") if upi_match else None
        }
        
        if is_bank_matched:
            matched_accounting.append(accounting_entry)
        else:
            unmatched_accounting.append(accounting_entry)

    return {
        "matched": result,
        "matched_accounting": matched_accounting,
        "unmatched_accounting": unmatched_accounting
    }