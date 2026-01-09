import requests
import re
import time
import os

def get_cik_from_ticker(ticker):
    """Get CIK number from ticker symbol"""
    try:
        cik_response = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={'User-Agent': 'Your Name email@example.com'}
        )
        
        if cik_response.status_code == 200:
            cik_data = cik_response.json()
            
            for company in cik_data.values():
                if company['ticker'] == ticker.upper():
                    cik = str(company['cik_str']).zfill(10)
                    print(f"Found {company['title']}: CIK={cik}")
                    return cik
            
        print(f"Ticker {ticker} not found in SEC database")
        return None
    except Exception as e:
        print(f"Error getting CIK for {ticker}: {e}")
        return None

def download_10k_filings(ticker, num_filings=5):
    """Download 10-K filings for a specific ticker"""
    
    # Get CIK first
    cik = get_cik_from_ticker(ticker)
    if not cik:
        return []
    
    try:
        # Get company submissions
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        
        headers = {
            'User-Agent': 'Your Name email@example.com',
            'Accept-Encoding': 'gzip, deflate'
        }
        
        response = requests.get(submissions_url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to get submissions: {response.status_code}")
            return []
        
        data = response.json()
        
        # Get recent filings
        recent_filings = data.get('filings', {}).get('recent', {})
        
        if not recent_filings:
            print("No recent filings found")
            return []
        
        # Create download directory
        download_dir = f"10K_downloads/{ticker}"
        os.makedirs(download_dir, exist_ok=True)
        
        downloaded_files = []
        
        # Find 10-K filings
        if 'form' in recent_filings:
            form_list = recent_filings['form']
            accession_list = recent_filings['accessionNumber']
            filing_date_list = recent_filings.get('filingDate', [])
            primary_doc_list = recent_filings.get('primaryDocument', [])
            
            for i in range(len(form_list)):
                if form_list[i] == '10-K' and len(downloaded_files) < num_filings:
                    if i < len(accession_list) and i < len(filing_date_list) and i < len(primary_doc_list):
                        accession = accession_list[i].replace('-', '')
                        filing_date = filing_date_list[i]
                        primary_doc = primary_doc_list[i]
                        
                        if primary_doc:
                            # Download the filing
                            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"
                            
                            print(f"Downloading 10-K from {filing_date}...")
                            
                            file_response = requests.get(
                                filing_url, 
                                headers={'User-Agent': 'Your Name email@example.com'}
                            )
                            
                            if file_response.status_code == 200:
                                # Save file
                                filename = f"{download_dir}/10K_{filing_date}.txt"
                                with open(filename, 'w', encoding='utf-8') as f:
                                    f.write(file_response.text)
                                
                                downloaded_files.append(filename)
                                print(f"  Saved: {filename}")
                                
                                # Rate limiting
                                time.sleep(0.1)
        
        return downloaded_files
        
    except Exception as e:
        print(f"Error downloading filings for {ticker}: {e}")
        return []

# Example usage
if __name__ == "__main__":
    # Configure your user agent
    # IMPORTANT: Replace with your actual name and email
    print("SEC EDGAR 10-K Downloader")
    print("=" * 40)
    
    # Companies to download
    companies = ["PGR", "BRK-B", "KNSL"]
    
    # Download filings
    for ticker in companies:
        print(f"\nProcessing {ticker}...")
        files = download_10k_filings(ticker, num_filings=3)
        print(f"  Downloaded {len(files)} filings")
    
    print("\nAll downloads complete!")
    print("Files saved in: 10K_downloads/")
