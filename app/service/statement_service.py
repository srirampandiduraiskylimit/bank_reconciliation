import pandas as pd
import re
import numpy as np


class StatementParser:

    ROLE_ALIASES = {
        "date": ["date", "tran date", "transaction date", "value date", "posting date"],
        "description": ["narration", "particulars", "description", "details", "transaction", "remarks", "description (narration)"],
        "debit": ["debit", "dr", "withdrawal", "withdrawals", "paid out", "withdraw", "debit (withdrawal)", "debit (withdrawal) ₹"],
        "credit": ["credit", "cr", "deposit", "deposits", "received", "deposit amount", "credit (deposit)", "credit (deposit) ₹"],
        "balance": ["balance", "closing balance", "bal", "available balance", "running balance", "balance ₹"],
        "reference": ["chq", "cheque", "ref", "reference", "utr", "txn id", "trn id"],
    }

    # =========================
    # MAIN PIPELINE
    # =========================
    @classmethod
    def extract_transactions(cls, file_path):

        sheets = cls._load(file_path)

        all_transactions = []
        schema = {}

        for sheet_name, df in sheets.items():

            # Clean the dataframe
            df = df.fillna("")
            
            # Try to find header row
            header_idx = cls._find_header_row(df)

            if header_idx is None:
                # Try alternative header detection
                header_idx = cls._find_header_row_alternative(df)
                
            if header_idx is None:
                continue

            # Get headers
            headers = df.iloc[header_idx].astype(str).tolist()
            headers = [str(h).strip() for h in headers]
            headers = cls._make_unique(headers)

            # Get data rows
            data = df.iloc[header_idx + 1:].copy()
            data.columns = headers
            data.reset_index(drop=True, inplace=True)

            # Map columns - specifically for your column names
            column_map = cls._map_columns_for_bank_statement(headers)
            
            # If mapping is incomplete, try to infer
            if len(column_map) < 3:
                column_map = cls._infer_columns(data, headers)
            
            schema[sheet_name] = column_map

            # Extract transactions
            rows = cls._extract_rows(data, column_map)
            all_transactions.extend(rows)

        return {
            "success": True,
            "total_records": len(all_transactions),
            "detected_columns": schema,
            "transactions": all_transactions
        }

    # =========================
    # LOAD
    # =========================
    @staticmethod
    def _load(file_path):
        if file_path.endswith(".csv"):
            return {"Sheet1": pd.read_csv(file_path, header=None, dtype=str)}

        xls = pd.ExcelFile(file_path)
        return {
            sheet: pd.read_excel(file_path, sheet_name=sheet, header=None, dtype=str)
            for sheet in xls.sheet_names
        }

    # =========================
    # HEADER DETECTION
    # =========================
    @classmethod
    def _find_header_row(cls, df):
        for i in range(min(len(df), 50)):
            row = df.iloc[i].fillna("").astype(str).str.lower()
            text = " ".join(row)
            
            # Check for your specific header pattern
            if ("date" in text and 
                "description" in text and 
                "debit" in text and 
                "credit" in text and 
                "balance" in text):
                return i
        return None

    # =========================
    # HEADER DETECTION (ALTERNATIVE)
    # =========================
    @classmethod
    def _find_header_row_alternative(cls, df):
        for i in range(min(len(df), 30)):
            row = df.iloc[i].fillna("").astype(str).str.lower()
            row_text = " ".join(row)
            
            # Look for specific column names
            if ("date" in row_text and 
                ("description" in row_text or "narration" in row_text) and
                ("debit" in row_text or "withdrawal" in row_text) and
                ("credit" in row_text or "deposit" in row_text) and
                ("balance" in row_text)):
                return i
        return None

    # =========================
    # MAP COLUMNS FOR BANK STATEMENT (SPECIFIC)
    # =========================
    @classmethod
    def _map_columns_for_bank_statement(cls, headers):
        mapping = {}
        
        for idx, header in enumerate(headers):
            header_lower = str(header).lower().strip()
            
            # Exact match for your column names
            if "date" in header_lower:
                mapping["date"] = header
            elif "description" in header_lower or "narration" in header_lower:
                mapping["description"] = header
            elif "debit" in header_lower or "withdrawal" in header_lower:
                mapping["debit"] = header
            elif "credit" in header_lower or "deposit" in header_lower:
                mapping["credit"] = header
            elif "balance" in header_lower:
                mapping["balance"] = header
            elif "reference" in header_lower or "ref" in header_lower or "utr" in header_lower:
                mapping["reference"] = header
        
        return mapping

    # =========================
    # INFER COLUMNS
    # =========================
    @classmethod
    def _infer_columns(cls, df, headers):
        mapping = {}
        
        for idx, header in enumerate(headers):
            header_lower = str(header).lower().strip()
            
            # Check if column contains dates
            if "date" in header_lower:
                mapping["date"] = header
                continue
            
            # Check if column contains descriptions
            if any(word in header_lower for word in ["description", "narration", "particulars", "details"]):
                mapping["description"] = header
                continue
            
            # Check for amount columns
            sample = df[header].dropna().astype(str).head(20)
            if len(sample) > 0:
                # Check if column has numeric values
                cleaned = sample.str.replace(",", "").str.replace("₹", "").str.replace(" ", "").str.strip()
                is_numeric = cleaned.str.match(r'^-?\d+(\.\d+)?$')
                
                if is_numeric.mean() > 0.5:
                    # Check column name for hints
                    if "balance" in header_lower or "bal" in header_lower:
                        mapping["balance"] = header
                    elif "debit" in header_lower or "withdrawal" in header_lower:
                        mapping["debit"] = header
                    elif "credit" in header_lower or "deposit" in header_lower:
                        mapping["credit"] = header
                    else:
                        # Infer by position - usually debit, credit, balance in that order
                        pass
        
        # If still missing, use position-based inference
        amount_cols = [h for h in headers if h not in mapping.values()]
        amount_cols_found = []
        
        for h in amount_cols:
            sample = df[h].dropna().astype(str)
            if len(sample) > 0:
                cleaned = sample.str.replace(",", "").str.replace("₹", "").str.strip()
                is_numeric = cleaned.str.match(r'^-?\d+(\.\d+)?$')
                if is_numeric.mean() > 0.5:
                    amount_cols_found.append(h)
        
        # Assign debit, credit, balance in order
        if len(amount_cols_found) >= 3:
            if "debit" not in mapping:
                mapping["debit"] = amount_cols_found[0]
            if "credit" not in mapping:
                mapping["credit"] = amount_cols_found[1]
            if "balance" not in mapping:
                mapping["balance"] = amount_cols_found[2]
        elif len(amount_cols_found) == 2:
            if "debit" not in mapping:
                mapping["debit"] = amount_cols_found[0]
            if "credit" not in mapping:
                mapping["credit"] = amount_cols_found[1]
        
        return mapping

    # =========================
    # EXTRACT ROWS
    # =========================
    @classmethod
    def _extract_rows(cls, df, mapping):
        rows = []
        
        # Ensure all required columns exist
        required = ["date", "description", "debit", "credit"]
        for req in required:
            if req not in mapping:
                # Try to find by common names
                for col in df.columns:
                    col_lower = str(col).lower()
                    if req == "date" and "date" in col_lower:
                        mapping[req] = col
                    elif req == "description" and any(word in col_lower for word in ["description", "narration", "particulars"]):
                        mapping[req] = col
                    elif req == "debit" and any(word in col_lower for word in ["debit", "withdrawal"]):
                        mapping[req] = col
                    elif req == "credit" and any(word in col_lower for word in ["credit", "deposit"]):
                        mapping[req] = col
        
        # If still missing required columns, return empty
        if not all(req in mapping for req in required):
            return rows
        
        # Extract rows
        for _, row in df.iterrows():
            try:
                date = str(row.get(mapping.get("date", ""), "")).strip()
                description = str(row.get(mapping.get("description", ""), "")).strip()
                
                # Parse amounts - IMPORTANT: these are the columns with amounts
                debit_str = str(row.get(mapping.get("debit", ""), "")).strip()
                credit_str = str(row.get(mapping.get("credit", ""), "")).strip()
                balance_str = str(row.get(mapping.get("balance", ""), "")).strip()
                reference = str(row.get(mapping.get("reference", ""), "")).strip()
                
                # Skip if no data
                if not description and not debit_str and not credit_str:
                    continue
                
                # Parse amounts
                debit = cls._parse_amount(debit_str)
                credit = cls._parse_amount(credit_str)
                
                # Skip opening/closing balance
                if "opening balance" in description.lower() or "closing balance" in description.lower():
                    continue
                
                # Only include transactions with amounts or invoice/expense references
                if debit == 0 and credit == 0:
                    # Check if description indicates a transaction
                    desc_lower = description.lower()
                    if "invoice" not in desc_lower and "inv" not in desc_lower and "exp" not in desc_lower:
                        continue
                
                rows.append({
                    "date": date,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance_str,
                    "reference": reference
                })
            except Exception as e:
                # Skip problematic rows
                continue
        
        return rows

    # =========================
    # PARSE AMOUNT
    # =========================
    @staticmethod
    def _parse_amount(value):
        try:
            if not value or str(value).strip() == "":
                return 0.0
            
            # Handle various formats
            cleaned = str(value).strip()
            
            # Remove currency symbols, commas, and extra spaces
            cleaned = cleaned.replace(",", "")
            cleaned = cleaned.replace("₹", "")
            cleaned = cleaned.replace("$", "")
            cleaned = cleaned.replace(" ", "")
            
            # Handle negative values in parentheses (e.g., (1,234.56))
            if cleaned.startswith("(") and cleaned.endswith(")"):
                cleaned = "-" + cleaned[1:-1]
            
            # Handle CR/DR suffixes
            if cleaned.upper().endswith("CR"):
                cleaned = cleaned[:-2].strip()
            elif cleaned.upper().endswith("DR"):
                cleaned = "-" + cleaned[:-2].strip()
            
            # Convert to float
            return float(cleaned) if cleaned else 0.0
        except:
            return 0.0

    # =========================
    # UNIQUE HEADERS
    # =========================
    @staticmethod
    def _make_unique(headers):
        seen = {}
        out = []
        
        for h in headers:
            h = str(h).strip()
            
            if h not in seen:
                seen[h] = 0
                out.append(h)
            else:
                seen[h] += 1
                out.append(f"{h}_{seen[h]}")
        
        return out