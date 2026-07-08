"""Read Budget_File.xlsx and extract the data table from the
"Master Summary Radio - Station" sheet by locating the "Market" header cell.
"""

import pandas as pd

REQUIRED_COLUMNS = [
    "Market", "Station", "Metric", "Product",
    "Jan-26", "Feb-26", "Mar-26", "Apr-26", "May-26", "Jun-26",
    "Jul-26", "Aug-26", "Sep-26", "Oct-26", "Nov-26", "Dec-26",
    "2026B",
]


def read_market_table(file_path: str,
                      sheet_name: str,
                      anchor: str) -> pd.DataFrame:
    """Load the sheet, find the cell containing `anchor` (e.g. "Market"),
    and return the data block starting at that cell as a DataFrame with
    the anchor row as headers.
    """
    # Read the whole sheet without assuming any header, so we can search
    # for the anchor cell ourselves.
    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

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
    import datetime as _dt
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


if __name__ == "__main__":
    df = read_market_table(
        "Budget_File.xlsx",
        sheet_name="Master Summary Radio - Station",
        anchor="Market",
    )
    print(f"Shape: {df.shape}")
    print(df.to_string(index=False))
