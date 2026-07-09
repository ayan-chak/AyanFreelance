"""Read a Budget xlsx file from Google Cloud Storage and extract the data
table from the "Master Summary Radio - Station" sheet by locating the
"Market" header cell.

Designed to run as a Google Cloud Function: the file is loaded from a GCS
bucket into memory rather than from a local path.
"""
import functions_framework
import logging
from google.cloud import bigquery
from google.auth import default
from google.auth.impersonated_credentials import Credentials
from datetime import datetime, timezone


import datetime as _dt
import io

import pandas as pd
from google.cloud import storage

REQUIRED_COLUMNS = [
    "Market", "Station", "Metric", "Product",
    "Jan-26", "Feb-26", "Mar-26", "Apr-26", "May-26", "Jun-26",
    "Jul-26", "Aug-26", "Sep-26", "Oct-26", "Nov-26", "Dec-26",
    "2026B",
]

DESTINATION_PROJECT = "cmg-uber-global"
DESTINATION_DATASET = "Budget_2026"
DESTINATION_TABLENAME = "BUDGET_TV_RADIO"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _bq_safe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with column names valid for BigQuery.

    BigQuery column names must match `[A-Za-z_][A-Za-z0-9_]*`, so replace
    hyphens with underscores and prefix names that start with a digit.
    """
    renamed = {}
    for col in df.columns:
        name = str(col).replace("-", "_").replace(" ", "_")
        if name and name[0].isdigit():
            name = f"Y_{name}"
        renamed[col] = name
    return df.rename(columns=renamed)


def load_to_bigquery(df: pd.DataFrame) -> str:
    """Load `df` into the destination BigQuery table (truncate + reload)."""
    client = bigquery.Client(project=DESTINATION_PROJECT)
    table_id = f"{DESTINATION_PROJECT}.{DESTINATION_DATASET}.{DESTINATION_TABLENAME}"

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )

    job = client.load_table_from_dataframe(
        _bq_safe_columns(df), table_id, job_config=job_config
    )
    job.result()

    table = client.get_table(table_id)
    logger.info("Loaded %d rows into %s", table.num_rows, table_id)
    return table_id


def _json_safe(value):
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)

def download_blob_to_memory(bucket_name: str, blob_name: str):
    """Download `blob_name` from GCS bucket `bucket_name` into an in-memory
    BytesIO buffer suitable for `pd.read_excel`.
    """
    client = storage.Client()
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob(blob_name)
    data = blob.download_as_bytes()
    return io.BytesIO(data)


def read_market_table(file_obj,
                      sheet_name: str,
                      anchor: str):
    """Load the sheet from a file path or binary file-like object, find the
    cell containing `anchor` (e.g. "Market"), and return the data block
    starting at that cell as a DataFrame with the anchor row as headers.
    """
    # Read the whole sheet without assuming any header, so we can search
    # for the anchor cell ourselves.
    raw = pd.read_excel(file_obj, sheet_name=sheet_name, header=None)

    # Locate the "Market" cell.
    match = raw.astype(str).apply(lambda col: col.str.strip() == anchor)
    if not match.any().any():
        raise ValueError(f"Could not find anchor cell '{anchor}' "
                         f"in sheet '{sheet_name}'.")

    header_row, header_col = [(r, c) for r in match.index
                              for c in match.columns if match.at[r, c]][0]

    # Slice from the anchor cell to the bottom-right of the sheet.
    block = raw.iloc[header_row:, header_col:].reset_index(drop=True)

    # Promote the first row to column headers, drop it from the data.
    block.columns = block.iloc[0]
    block = block.iloc[1:].reset_index(drop=True)

    # Drop rows/cols that are completely empty.
    block = block.dropna(how="all").dropna(axis=1, how="all")
    block.columns.name = None

    # Normalize datetime column headers to `MMM-YY` (e.g. Jan-26).
    block.columns = [
        col.strftime("%b-%y") if isinstance(col, (pd.Timestamp, _dt.datetime, _dt.date)) else col
        for col in block.columns
    ]

    # Keep only the required columns, preserving the requested order.
    missing = [c for c in REQUIRED_COLUMNS if c not in block.columns]
    if missing:
        raise ValueError(f"Missing expected columns in sheet "
                         f"'{sheet_name}': {missing}")
    block = block[REQUIRED_COLUMNS]

    return block


def read_budget_from_gcs(bucket_name: str,
                         blob_name: str,
                         sheet_name: str,
                         anchor: str):
    """Download the budget xlsx from GCS and return the parsed DataFrame."""
    buffer = download_blob_to_memory(bucket_name, blob_name)
    return read_market_table(buffer, sheet_name=sheet_name, anchor=anchor)


def budget_handler(request):
    """Google Cloud Function HTTP entry point.

    Expects JSON body with keys: `bucket`, `blob`, `sheet_name`, `anchor`.
    Returns the parsed DataFrame as JSON records.
    """
    payload = request.get_json(silent=True) or {}
    bucket_name = payload.get("bucket", "cmg-uber-global")
    blob_name = payload.get("blob", "Budget/Incoming/Budget_File.xlsx")
    sheet_name = payload.get("sheet_name", "Master Summary Radio - Station")
    anchor = payload.get("anchor", "Market")

    df = read_budget_from_gcs(bucket_name, blob_name, sheet_name, anchor)
    load_to_bigquery(df)
    return df.to_json(orient="records"), 200, {"Content-Type": "application/json"}
 
 
@functions_framework.http
def run_main(request):

    try:
        df = read_budget_from_gcs(
            bucket_name="cmg-uber-global",
            blob_name="Budget/Incoming/Budget_File.xlsx",
            sheet_name="Master Summary Radio - Station",
            anchor="Market",
        )
        
        logger.info("Shape: %s", df.shape)
        logger.info("Row/column counts:\n%s", df.count())
        logger.info("DataFrame:\n%s", df.to_string(index=False))

        return _json_safe(
            {
                "status": "success",
                "message": "Budget File loaded Successfully",
            }
        )

    except Exception as e:
        logger.exception("Budget file load failed")
        return _json_safe(
            {
                "status": "error",
                "message": str(e),
            }
        )
