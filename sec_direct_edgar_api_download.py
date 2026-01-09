import requests
import re
import time
from bs4 import BeautifulSoup
import os

def get_10k_filings(ticker, num_filings=10):
    """
    Download 10-K filings for a given ticker symbol
    """
    
    # SEC EDGAR company lookup URL
    cik_lookup_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}"
    
    try:
        response = requests.get(cik_lookup_url, headers={'User-Agent': 'FUNAIBUDDY spreadhappinesstoall062@gmail.com'})
        response.raise_for_status()
        
        # Extract CIK number
        cik_match = re.search(r'CIK=(\d{10})', response.text)
        if not cik_match:
            print(f"Could not find CIK for {ticker}")
            return []
        
        cik = cik_match.group(1)
        print(f"Found CIK for {ticker}: {cik}")
        
        # Search for 10-K filings
        filings_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        
        headers = {
            'User-Agent': 'Your Name email@example.com',
            'Accept-Encoding': 'gzip, deflate',
            'Host': 'data.sec.gov'
        }
        
        filings_response = requests.get(filings_url, headers=headers)
        filings_response.raise_for_status()
        data = filings_response.json()
        
        # Get recent filings
        recent_filings = data.get('filings', {}).get('recent', {})
        
        # Create directory for downloads
        os.makedirs(f"10K_downloads/{ticker}", exist_ok=True)
        
        downloaded_files = []
        
        # Find and download 10-K filings
        for i, form in enumerate(recent_filings['form']):
            if form == '10-K' and len(downloaded_files) < num_filings:
                accession_number = recent_filings['accessionNumber'][i].replace('-', '')
                filing_date = recent_filings['filingDate'][i]
                primary_document = recent_filings['primaryDocument'][i]
                
                # Construct the filing URL
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number}/{primary_document}"
                
                print(f"Downloading 10-K from {filing_date}...")
                
                # Download the filing
                file_response = requests.get(filing_url, headers={'User-Agent': 'Your Name email@example.com'})
                
                if file_response.status_code == 200:
                    # Save the file
                    filename = f"10K_downloads/{ticker}/10K_{filing_date}_{accession_number}.txt"
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(file_response.text)
                    downloaded_files.append(filename)
                    print(f"Saved: {filename}")
                    
                    # Respect SEC's rate limiting
                    time.sleep(0.1)
                else:
                    print(f"Failed to download: {filing_url}")
        
        return downloaded_files
        
    except Exception as e:
        print(f"Error downloading filings for {ticker}: {e}")
        return []

# Example usage
if __name__ == "__main__":
    # Download 10-K filings for Apple
    files = get_10k_filings("PGR", num_filings=5)
    print(f"Downloaded {len(files)} files")
