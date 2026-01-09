from sec_edgar_downloader import Downloader
import os

# Initialize downloader
dl = Downloader("FUNAIBUDDY", "spreadhappinesstoall062@gmail.com")

# Download 10-K filings for specific companies
companies = ["PGR", "BRK-B", "KNSL", "COST"]

for ticker in companies:
    print(f"Downloading 10-K filings for {ticker}...")
    
    # Get latest 5 10-K filings
    dl.get("10-K", ticker, limit=5)
    
    # Optional: Download specific years
    # dl.get("10-K", ticker, before_date="2019-12-31", after_date="2025-01-09")

print("Download complete!")
