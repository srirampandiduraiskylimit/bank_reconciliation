# app/service/upi_statement_service.py

import pandas as pd


class UPIStatementService:

    @staticmethod
    def _normalize_header(value):
        return str(value or "").strip().lower().replace(" ", "")

    @classmethod
    def _resolve_column(cls, columns, aliases):
        normalized = {cls._normalize_header(col): col for col in columns}
        for alias in aliases:
            key = cls._normalize_header(alias)
            if key in normalized:
                return normalized[key]
        return None

    @classmethod
    def extract_transactions(cls, file_path):
        try:
            if file_path.endswith(".csv"):
                df = pd.read_csv(file_path, dtype=str)
            else:
                df = pd.read_excel(file_path, dtype=str)

            df = df.fillna("")
            columns = list(df.columns)

            date_col = cls._resolve_column(columns, ["creation time", "date", "transaction date"])
            description_col = cls._resolve_column(columns, ["payer/receiver", "description", "payer receiver"])
            upi_id_col = cls._resolve_column(columns, ["paid via", "upi id", "upiid"])
            transaction_id_col = cls._resolve_column(columns, ["transaction id", "txn id", "transactionid"])
            amount_col = cls._resolve_column(columns, ["amount", "amt"])
            type_col = cls._resolve_column(columns, ["type"])
            status_col = cls._resolve_column(columns, ["status"])
            notes_col = cls._resolve_column(columns, ["notes", "note"])

            transactions = []

            for _, row in df.iterrows():
                transactions.append({
                    "date": str(row.get(date_col, "") if date_col else "").strip(),
                    "description": str(row.get(description_col, "") if description_col else "").strip(),
                    "upi_id": str(row.get(upi_id_col, "") if upi_id_col else "").strip(),
                    "transaction_id": str(row.get(transaction_id_col, "") if transaction_id_col else "").strip(),
                    "amount": cls.safe_float(row.get(amount_col, "") if amount_col else ""),
                    "type": str(row.get(type_col, "") if type_col else "").strip(),
                    "status": str(row.get(status_col, "") if status_col else "").strip(),
                    "notes": str(row.get(notes_col, "") if notes_col else "").strip(),
                })

            return {
                "success": True,
                "total_records": len(transactions),
                "transactions": transactions
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "transactions": []
            }

    @staticmethod
    def safe_float(value):
        try:
            if value is None:
                return 0.0

            return float(
                str(value)
                .replace(",", "")
                .replace("₹", "")
                .strip()
            )
        except Exception:
            return 0.0