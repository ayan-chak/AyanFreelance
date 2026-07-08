"""Read Budget_File.xlsx and extract the data table from the
"Master Summary Radio - Station" sheet by locating the "Market" header cell.
"""

import pandas as pd


def read_market_table(file_path: str,
                      sheet_name: str = "Master Summary Radio - Station",
                      anchor: str = "Market") -> pd.DataFrame:
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

    return block


if __name__ == "__main__":
    df = read_market_table("Budget_File.xlsx")
    print(f"Shape: {df.shape}")
    print(df.to_string(index=False))
