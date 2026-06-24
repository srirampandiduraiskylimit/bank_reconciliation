from datetime import datetime


def safe_float(value):
    try:
        if value is None:
            return 0.0
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except:
        return 0.0


def normalize_date(date_value):
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
        except:
            continue

    return date_value


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

    # Create a lookup for accounting entries by date and amount for better matching
    account_lookup = {}
    
    for item in accounts_data:
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
            "original": item
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
                "missing_transaction": True,
                "reason": "Zero amount transaction - skipped"
            })
            continue

        matched = False
        match_type = None
        matched_ref = None
        matched_item = None

        # Look for matching accounting entry by date and amount
        lookup_key = f"{tx_date}_{amount:.2f}"
        
        if lookup_key in account_lookup:
            candidates = account_lookup[lookup_key]
            
            # Find the best match based on transaction type
            for candidate in candidates:
                candidate_type = candidate["type"]
                
                # For credit transactions, match with invoices or capital
                if is_credit and candidate_type in ["invoice", "capital"]:
                    matched = True
                    match_type = candidate_type
                    matched_ref = candidate["ref_no"]
                    matched_item = candidate["original"]
                    break
                
                # For debit transactions, match with expenses
                elif is_debit and candidate_type == "expense":
                    matched = True
                    match_type = "expense"
                    matched_ref = candidate["ref_no"]
                    matched_item = candidate["original"]
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
            "missing_transaction": not matched,
            "reason": f"Matched with {match_type} - {matched_ref}" if matched else "No matching accounting entry found"
        }

        # Suggest action for unmatched transactions
        if not matched:
            if is_credit:
                result_entry["add_invoice"] = True
                result_entry["reason"] = f"Unmatched credit of {amount} - consider adding invoice"
            elif is_debit:
                result_entry["add_expense"] = True
                result_entry["reason"] = f"Unmatched debit of {amount} - consider adding expense"

        result.append(result_entry)

    return result