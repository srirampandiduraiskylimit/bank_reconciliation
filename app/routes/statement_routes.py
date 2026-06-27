import json
import logging
import os
import shutil
import time
import uuid

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

from app.service.statement_service import StatementParser
from app.service.account_statement_service import reconcile_bank_and_upi, reconcile_transactions
from app.service.upi_statement_service import UPIStatementService

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
    accounting_json: str = Form(...),
    upi_file: UploadFile | None = File(None)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'.")

    file_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}{ext}")
    upi_file_path = None

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        await file.close()

        if upi_file is not None and getattr(upi_file, "filename", None):
            upi_ext = os.path.splitext(upi_file.filename)[1].lower()
            if upi_ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"Unsupported UPI file type '{upi_ext}'.")

            upi_file_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}{upi_ext}")
            with open(upi_file_path, "wb") as buffer:
                shutil.copyfileobj(upi_file.file, buffer)
            await upi_file.close()

        result = StatementParser.extract_transactions(file_path)
        transactions = result.get("transactions", [])

        valid_transactions = []
        for tx in transactions:
            tx["debit"] = safe_float(tx.get("debit"))
            tx["credit"] = safe_float(tx.get("credit"))
            valid_transactions.append(tx)

        upi_transactions = []
        upi_error = None
        if upi_file_path:
            upi_result = UPIStatementService.extract_transactions(upi_file_path)
            upi_transactions = upi_result.get("transactions", [])
            if not upi_result.get("success"):
                upi_error = upi_result.get("error")

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
        
        reconciliation_result = reconcile_transactions(
            valid_transactions, 
            accounting_data,
            upi_transactions
        )
        
        matched_items = reconciliation_result["matched"]
        matched_accounting = reconciliation_result["matched_accounting"]
        unmatched_accounting = reconciliation_result["unmatched_accounting"]
        
        bank_upi_reconciliation = reconcile_bank_and_upi(
            valid_transactions,
            upi_transactions,
            accounting_data
        )

        matched_count = sum(1 for x in matched_items if x["matched"])
        unmatched_count = len(matched_items) - matched_count
        
        matched_accounting_count = len(matched_accounting)
        unmatched_accounting_count = len(unmatched_accounting)

        matched_invoice_count = sum(
            1 for x in matched_items if x.get("match_type") == "invoice"
        )

        matched_expense_count = sum(
            1 for x in matched_items if x.get("match_type") == "expense"
        )

        matched_capital_count = sum(
            1 for x in matched_items if x.get("match_type") == "capital"
        )

        return JSONResponse({
            "success": "true",
            "filename": file.filename,
            "total_records": len(valid_transactions),

            "detected_columns": result.get(
                "detected_columns",
                result.get("schema", {})
            ),

            "transactions": valid_transactions,

            "upi_file": (
                upi_file.filename
                if upi_file is not None and getattr(upi_file, "filename", None)
                else None
            ),

            "upi_transactions": upi_transactions,
            "upi_error": upi_error,

            "reconciliation_summary": {
                "total_bank_transactions": len(valid_transactions),
                "reconciled": matched_count,
                "pending_review": unmatched_count,
                "accounting_matched": matched_accounting_count,
                "accounting_pending": unmatched_accounting_count,
                "matched_invoice_count": matched_invoice_count,
                "matched_expense_count": matched_expense_count,
                "matched_capital_count": matched_capital_count,
                "upi_matched": bank_upi_reconciliation.get("matched_count", 0),
                "upi_pending": bank_upi_reconciliation.get("missing_count", 0),
            },

            "matched_items": [
                x for x in matched_items if x["matched"]
            ],

            "unmatched_items": [
                x for x in matched_items if not x["matched"]
            ],

            "matched_accounting": matched_accounting,
            "unmatched_accounting": unmatched_accounting,

            "bank_upi_reconciliation": {
                "matched_items": bank_upi_reconciliation.get("matched_items", []),
                "upi_missing_in_bank": bank_upi_reconciliation.get("upi_missing_in_bank", []),
                "bank_non_upi_transactions": bank_upi_reconciliation.get("bank_non_upi_transactions", []),
                "remarks": bank_upi_reconciliation.get("remarks", [])
            }
        })

    except Exception as e:
        logger.exception("Error processing file %s", file.filename)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        _safe_remove(file_path)
        if upi_file_path:
            _safe_remove(upi_file_path)