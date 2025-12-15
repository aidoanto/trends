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


def get_or_create_worksheet(spreadsheet, tab_name: str, rows: int = 100):
    """
    Get an existing worksheet or create a new one.
    """
    try:
        worksheet = spreadsheet.worksheet(tab_name)
        # Ensure worksheet has enough rows
        if worksheet.row_count < rows:
            worksheet.resize(rows=rows, cols=20)
    except gspread.WorksheetNotFound:
        print(f"  Creating new worksheet: {tab_name}")
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=rows, cols=20)
    return worksheet


def update_traffic_tab(spreadsheet, tab_name: str, keywords: list[str], interest_df: pd.DataFrame):
    """
    Update the traffic/interest over time tab.
    Headers on row 1, data starting row 2.
    """
    print(f"  Updating traffic tab: {tab_name}")
    
    worksheet = get_or_create_worksheet(spreadsheet, tab_name, rows=100)
    worksheet.clear()
    
    # Format data
    formatted_df = format_interest_data(interest_df, keywords)
    
    # Write data with headers on row 1
    set_with_dataframe(worksheet, formatted_df, row=1, col=1, include_index=False, include_column_header=True)
    
    print(f"  Successfully updated {tab_name}")


def update_related_tab(spreadsheet, tab_name: str, keywords: list[str], related_queries: dict):
    """
    Update the related queries tab.
    Headers on row 1, data starting row 2.
    """
    print(f"  Updating related tab: {tab_name}")
    
    worksheet = get_or_create_worksheet(spreadsheet, tab_name, rows=200)
    worksheet.clear()
    
    # Format data
    related_df = format_related_queries(related_queries, keywords)
    
    # Write data with headers on row 1
    set_with_dataframe(worksheet, related_df, row=1, col=1, include_index=False, include_column_header=True)
    
    print(f"  Successfully updated {tab_name}")


def update_log_tab(spreadsheet, topics_config: dict):
    """
    Update the log/metadata tab with update history and configuration.
    """
    print("Updating log tab...")
    
    worksheet = get_or_create_worksheet(spreadsheet, "Update Log", rows=50)
    worksheet.clear()
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Build log data
    log_data = [
        ["Last Updated", current_time],
        ["", ""],
        ["Topics Tracked", "Keywords"],
    ]
    
    for topic, config in topics_config.items():
        log_data.append([topic, ", ".join(config["keywords"])])
    
    log_data.append(["", ""])
    log_data.append(["Sheets Structure", ""])
    log_data.append(["- Traffic sheets", "Interest over time (last 24 hours)"])
    log_data.append(["- Related sheets", "Top and rising related queries"])
    
    worksheet.update(range_name="A1", values=log_data)
    print("  Successfully updated Update Log")


def update_tabs_for_topic(spreadsheet, base_tab_name: str, keywords: list[str]):
    """
    Update both traffic and related tabs for a topic.
    """
    print(f"Updating tabs for: {base_tab_name}")
    
    # Fetch trends data once for both tabs
    print(f"  Fetching trends for: {keywords}")
    try:
        data = fetch_trends_data(keywords)
    except Exception as e:
        print(f"  Error fetching trends: {e}")
        # Write error to traffic tab
        worksheet = get_or_create_worksheet(spreadsheet, base_tab_name)
        worksheet.clear()
        error_df = pd.DataFrame({
            "Error": [str(e)],
            "Last Attempt": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
        })
        set_with_dataframe(worksheet, error_df, row=1, col=1, include_index=False, include_column_header=True)
        return
    
    # Update traffic tab (main tab name)
    update_traffic_tab(spreadsheet, base_tab_name, keywords, data["interest_over_time"])
    
    # Update related queries tab (with " - Related" suffix)
    related_tab_name = f"{base_tab_name} - Related"
    update_related_tab(spreadsheet, related_tab_name, keywords, data["related_queries"])
    
    print(f"  Successfully updated both tabs for {base_tab_name}")


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
    
    # Update each topic (creates both traffic and related tabs)
    for tab_name, config in TABS_CONFIG.items():
        print(f"\n{'─' * 40}")
        try:
            update_tabs_for_topic(spreadsheet, tab_name, config["keywords"])
        except Exception as e:
            print(f"Error updating {tab_name}: {e}")
            # Continue with other topics even if one fails
            continue
        
        # Small delay between topics to avoid rate limiting
        sleep(2)
    
    # Update the log/metadata tab
    print(f"\n{'─' * 40}")
    try:
        update_log_tab(spreadsheet, TABS_CONFIG)
    except Exception as e:
        print(f"Error updating log tab: {e}")
    
    print(f"\n{'=' * 50}")
    print("Update complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
