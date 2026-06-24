import json
import logging
import os
import shutil
import time
import uuid

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

from app.service.statement_service import StatementParser
from app.service.account_statement_service import reconcile_transactions

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _safe_remove(path: str, retries: int = 5, delay: float = 0.2):
    for attempt in range(retries):
        try:
            os.remove(path)
            return
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(delay)
        except FileNotFoundError:
            return


def safe_float(value):
    try:
        if value is None:
            return 0.0
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except Exception:
        return 0.0


@router.post("/upload")
async def upload_statement(
    file: UploadFile = File(...),
    accounting_json: str = Form(...)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'.")

    file_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}{ext}")

    try:
        # ---------------- SAVE FILE ----------------
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        await file.close()

        # ---------------- PARSE BANK STATEMENT ----------------
        result = StatementParser.extract_transactions(file_path)
        transactions = result.get("transactions", [])

        valid_transactions = []
        for tx in transactions:
            tx["debit"] = safe_float(tx.get("debit"))
            tx["credit"] = safe_float(tx.get("credit"))
            valid_transactions.append(tx)

        # ---------------- PARSE ACCOUNTING JSON ----------------
        try:
            accounting_payload = json.loads(accounting_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid accounting_json.")

        accounting_data = (
            accounting_payload.get("data", [])
            if isinstance(accounting_payload, dict)
            else accounting_payload
            if isinstance(accounting_payload, list)
            else []
        )
        print(f"Received accounting records for reconciliation. - statement_routes.py:89", valid_transactions)
        # ---------------- RECONCILIATION ----------------
        reconciliation = reconcile_transactions(valid_transactions, accounting_data)

        # ---------------- COUNTS ----------------
        matched_count = sum(1 for x in reconciliation if x["matched"])
        unmatched_count = len(reconciliation) - matched_count

        matched_invoice_count = sum(
            1 for x in reconciliation if x.get("match_type") == "invoice"
        )

        matched_expense_count = sum(
            1 for x in reconciliation if x.get("match_type") == "expense"
        )

        matched_capital_count = sum(
            1 for x in reconciliation if x.get("match_type") == "capital"
        )

        # ---------------- CAPITAL FIX ----------------
        total_capital = sum(
            1 for x in accounting_data
            if str(x.get("type", "")).strip().lower() == "capital"
        )

        missing_capital_count = max(0, total_capital - matched_capital_count)

        missing_invoice_count = sum(1 for x in reconciliation if x.get("add_invoice"))
        missing_expense_count = sum(1 for x in reconciliation if x.get("add_expense"))

        # ---------------- RESPONSE ----------------
        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "total_records": len(valid_transactions),

            "detected_columns": result.get("schema", {}),

            "transactions": valid_transactions,

            "reconciliation": {
                "matched_count": matched_count,
                "unmatched_count": unmatched_count,

                "matched_invoice_count": matched_invoice_count,
                "matched_expense_count": matched_expense_count,
                "matched_capital_count": matched_capital_count,

                "missing_invoice_count": missing_invoice_count,
                "missing_expense_count": missing_expense_count,
                "missing_capital_count": missing_capital_count,

                "items": reconciliation
            }
        })

    except Exception as e:
        logger.exception("Error processing file %s", file.filename)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        _safe_remove(file_path)