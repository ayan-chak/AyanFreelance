"""Read the Budget Excel workbook and load it into BigQuery."""

import logging
import os
from datetime import datetime

import pandas as pd
from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SOURCE_FILE = os.environ.get("BUDGET_FILE", "Budget_File.xlsx")
SHEET_NAME = "Master Summary Radio - Station"

DESTINATION_PROJECT = "cmg-uber-global"
DESTINATION_DATASET = "Budget_2026"
DESTINATION_TABLENAME = "BUDGET_TV_RADIO"


def _clean_column(col):
    """Convert datetime column headers to `YYYY_MM` strings and normalize others."""
    if isinstance(col, (pd.Timestamp, datetime)):
        return col.strftime("M_%Y_%m")
    name = str(col).strip().replace(" ", "_")
    # BigQuery column names must start with a letter or underscore.
    if name and name[0].isdigit():
        name = f"Y_{name}"
    return name


def read_budget(source_file: str = SOURCE_FILE,
                sheet_name: str = SHEET_NAME) -> pd.DataFrame:
    """Read the budget sheet and return a cleaned DataFrame."""
    df = pd.read_excel(source_file, sheet_name=sheet_name, header=1)

    # Drop fully empty rows/columns and any pandas placeholder "Unnamed" columns.
    df = df.dropna(how="all")
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]

    df.columns = [_clean_column(c) for c in df.columns]

    # Coerce month value columns to numeric (Excel exports "-" for blanks).
    for col in df.columns:
        if col in {"Market", "Station", "Metric", "Product"}:
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.reset_index(drop=True)


def load_to_bigquery(df: pd.DataFrame) -> None:
    """Load the given DataFrame to the destination BigQuery table."""
    client = bigquery.Client(project=DESTINATION_PROJECT)
    table_id = f"{DESTINATION_PROJECT}.{DESTINATION_DATASET}.{DESTINATION_TABLENAME}"

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )

    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()

    table = client.get_table(table_id)
    logger.info("Loaded %d rows into %s", table.num_rows, table_id)


if __name__ == "__main__":
    df = read_budget()
    logger.info("Read %d rows from %r / sheet %r", len(df), SOURCE_FILE, SHEET_NAME)
    logger.info("DataFrame head:\n%s", df.head())
    logger.info("DataFrame count:\n%s", df.count())
    load_to_bigquery(df)
