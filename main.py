"""
Google Trends to Google Sheets Dashboard

Fetches Google Trends data for keywords related to:
1. Bondi Beach incident ("Bondi shooting")
2. Crisis support services ("Lifeline", "Crisis support")

Writes data to a Google Sheet for stakeholder monitoring.
"""

import json
import os
from datetime import datetime
from time import sleep

import gspread
import pandas as pd
from dotenv import load_dotenv
from gspread_dataframe import set_with_dataframe
from pytrends.request import TrendReq

# Load environment variables from .env file (for local development)
load_dotenv()

# Google Sheet configuration
SPREADSHEET_ID = "1aSC_o7FqYVTB9B96RJQGphhwzDGJfIbPAgTR5kXwKbo"

# Keyword configurations for each tab
TABS_CONFIG = {
    "Bondi Beach": {
        "keywords": ["Bondi shooting"],
        "description": "Incident monitoring",
    },
    "Crisis Support": {
        "keywords": ["Lifeline", "Crisis support"],
        "description": "Distress signals monitoring",
    },
}


def get_google_sheets_client():
    """
    Authenticate with Google Sheets using service account credentials.
    
    Credentials can come from:
    1. GOOGLE_SHEETS_CREDS environment variable (JSON string)
    2. GOOGLE_SHEETS_CREDS_FILE environment variable (path to JSON file)
    """
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDS")
    creds_file = os.environ.get("GOOGLE_SHEETS_CREDS_FILE")
    
    if creds_json:
        # Parse JSON string from environment variable
        creds_dict = json.loads(creds_json)
        client = gspread.service_account_from_dict(creds_dict)
    elif creds_file:
        # Load from file path
        client = gspread.service_account(filename=creds_file)
    else:
        raise ValueError(
            "No credentials found. Set GOOGLE_SHEETS_CREDS (JSON string) "
            "or GOOGLE_SHEETS_CREDS_FILE (path to JSON file)"
        )
    
    return client


def fetch_trends_data(keywords: list[str], timeframe: str = "now 1-d"):
    """
    Fetch Google Trends data for the given keywords.
    
    Args:
        keywords: List of keywords to search for
        timeframe: Time range for the data (default: last 24 hours)
        
    Returns:
        Dictionary containing:
        - interest_over_time: DataFrame with hourly interest data
        - related_queries: Dictionary of related queries per keyword
    """
    # Initialize pytrends
    pytrends = TrendReq(hl="en-AU", tz=600)  # Australian English, AEST timezone
    
    # Build payload with keywords
    pytrends.build_payload(keywords, cat=0, timeframe=timeframe, geo="AU")
    
    # Fetch interest over time
    interest_df = pytrends.interest_over_time()
    
    # Small delay to avoid rate limiting
    sleep(1)
    
    # Fetch related queries for each keyword
    related_queries = pytrends.related_queries()
    
    return {
        "interest_over_time": interest_df,
        "related_queries": related_queries,
    }


def format_interest_data(df: pd.DataFrame, keywords: list[str]) -> pd.DataFrame:
    """
    Format the interest over time DataFrame for display in Google Sheets.
    """
    if df.empty:
        return pd.DataFrame({"Message": ["No data available for this time period"]})
    
    # Reset index to make datetime a column
    df = df.reset_index()
    
    # Rename the date column
    df = df.rename(columns={"date": "Timestamp"})
    
    # Drop the 'isPartial' column if present
    if "isPartial" in df.columns:
        df = df.drop(columns=["isPartial"])
    
    # Format timestamp for readability
    df["Timestamp"] = df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M")
    
    return df


def format_related_queries(related_queries: dict, keywords: list[str]) -> pd.DataFrame:
    """
    Format related queries data into a single DataFrame for display.
    """
    rows = []
    
    for keyword in keywords:
        keyword_data = related_queries.get(keyword, {})
        
        # Top queries
        top_df = keyword_data.get("top")
        if top_df is not None and not top_df.empty:
            for _, row in top_df.head(10).iterrows():
                rows.append({
                    "Keyword": keyword,
                    "Type": "Top",
                    "Related Query": row.get("query", ""),
                    "Value": row.get("value", ""),
                })
        
        # Rising queries
        rising_df = keyword_data.get("rising")
        if rising_df is not None and not rising_df.empty:
            for _, row in rising_df.head(10).iterrows():
                rows.append({
                    "Keyword": keyword,
                    "Type": "Rising",
                    "Related Query": row.get("query", ""),
                    "Value": row.get("value", ""),
                })
    
    if not rows:
        return pd.DataFrame({"Message": ["No related queries found"]})
    
    return pd.DataFrame(rows)


def update_sheet_tab(spreadsheet, tab_name: str, keywords: list[str]):
    """
    Update a single tab in the Google Sheet with trends data.
    """
    print(f"Updating tab: {tab_name}")
    
    # Get or create the worksheet
    try:
        worksheet = spreadsheet.worksheet(tab_name)
        # Ensure worksheet has enough rows
        if worksheet.row_count < 500:
            worksheet.resize(rows=500, cols=20)
    except gspread.WorksheetNotFound:
        print(f"  Creating new worksheet: {tab_name}")
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=500, cols=20)
    
    # Clear existing content
    worksheet.clear()
    
    # Fetch trends data
    print(f"  Fetching trends for: {keywords}")
    try:
        data = fetch_trends_data(keywords)
    except Exception as e:
        print(f"  Error fetching trends: {e}")
        # Write error message to sheet
        worksheet.update(range_name="A1", values=[[f"Error fetching data: {e}"]])
        worksheet.update(range_name="A2", values=[[f"Last attempt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]])
        return
    
    # Format data
    interest_df = format_interest_data(data["interest_over_time"], keywords)
    related_df = format_related_queries(data["related_queries"], keywords)
    
    # Write header with timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    worksheet.update(range_name="A1", values=[[f"Last Updated: {current_time}"]])
    worksheet.update(range_name="A2", values=[[f"Keywords: {', '.join(keywords)}"]])
    
    # Write interest over time data
    worksheet.update(range_name="A4", values=[["INTEREST OVER TIME (Last 24 Hours)"]])
    set_with_dataframe(worksheet, interest_df, row=5, col=1)
    
    # Calculate where to put related queries (below interest data)
    related_start_row = 5 + len(interest_df) + 3
    
    # Write related queries data
    worksheet.update(range_name=f"A{related_start_row}", values=[["RELATED QUERIES"]])
    set_with_dataframe(worksheet, related_df, row=related_start_row + 1, col=1)
    
    print(f"  Successfully updated {tab_name}")


def main():
    """
    Main function to update all tabs in the Google Sheet.
    """
    print("=" * 50)
    print("Google Trends Dashboard Update")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    # Connect to Google Sheets
    print("\nConnecting to Google Sheets...")
    try:
        client = get_google_sheets_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        print(f"Connected to: {spreadsheet.title}")
    except Exception as e:
        print(f"Failed to connect to Google Sheets: {e}")
        raise
    
    # Update each tab
    for tab_name, config in TABS_CONFIG.items():
        print(f"\n{'─' * 40}")
        try:
            update_sheet_tab(spreadsheet, tab_name, config["keywords"])
        except Exception as e:
            print(f"Error updating {tab_name}: {e}")
            # Continue with other tabs even if one fails
            continue
        
        # Small delay between tabs to avoid rate limiting
        sleep(2)
    
    print(f"\n{'=' * 50}")
    print("Update complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
