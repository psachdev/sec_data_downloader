# 🔍 SEC EDGAR API Master: Download 10-K Filings & Company Financial Data

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![SEC API](https://img.shields.io/badge/SEC-EDGAR%20API-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Downloads](https://img.shields.io/badge/Downloads-10K%20Filings-orange.svg)

<!-- GitHub specific badges -->
![GitHub stars](https://img.shields.io/github/stars/psachdev/sec_data_downloader?style=social)
![GitHub forks](https://img.shields.io/github/forks/psachdev/sec_data_downloader?style=social)
![GitHub issues](https://img.shields.io/github/issues/psachdev/sec_data_downloader)
![GitHub last commit](https://img.shields.io/github/last-commit/psachdev/sec_data_downloader)

<!-- Size badges -->
![Code size](https://img.shields.io/github/languages/code-size/psachdev/sec_data_downloader)
![Repo size](https://img.shields.io/github/repo-size/psachdev/sec_data_downloader)

<!-- Activity badges -->
![GitHub contributors](https://img.shields.io/github/contributors/psachdev/sec_data_downloader)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/psachdev/sec_data_downloader)

## 🚀 The Ultimate SEC EDGAR API Toolkit for Financial Data Extraction

Welcome to the most comprehensive Python toolkit for downloading SEC EDGAR 10-K filings and extracting company financial data directly from the SEC EDGAR database. This repository provides everything you need to access SEC filings, parse 10-K documents, and analyze public company financial data with ease.

## 📈 Why This SEC EDGAR Toolkit Matters

In today's data-driven financial landscape, accessing SEC filings and analyzing 10-K documents is crucial for:

* Investment research and financial analysis
* Quantitative trading strategies
* Risk management and compliance monitoring
* Academic research in finance and economics
* AI-powered financial analysis (like the insights shared in our blog post: [The Rise of AI Copilots in Finance—OpenAI Leads the Way](https://funaibuddy.com/the-rise-of-ai-copilots-in-finance-openai-leads-the-way/))


## ✨ Key Features: Your Complete SEC EDGAR Solution

### 📋 Multiple Methods for Every Use Case

* Method 1: Professional-grade SEC API integration using [sec-api.io](https://sec-api.io/)
* Method 2: Simplified SEC EDGAR downloading with [sec-edgar-downloader](https://sec-edgar-downloader.readthedocs.io/)
* Method 3: Direct SEC EDGAR API access (no API key required)
* Method 4: Advanced company facts extraction from SEC filings

### 🔧 What You Can Do With This SEC EDGAR Toolkit

* Download 10-K filings for any public company
* Extract financial metrics from SEC filings
* Batch download multiple companies' SEC filings
* Access historical 10-K documents for trend analysis
* Parse structured financial data from company facts API
* Automate SEC data collection for your research pipeline

## 🚦 Quick Start: Download SEC Filings in 5 Minutes

### Prerequisites & Installation

```
# Clone the SEC EDGAR API repository
git clone git@github.com:psachdev/sec_data_downloader.git
cd sec_data_downloader

# Install required packages
pip install sec-api sec-edgar-downloader requests beautifulsoup4 pandas
```

### Basic Usage: Download 10-K Filings

```
from sec_edgar_downloader import Downloader

# Initialize the SEC EDGAR downloader
dl = Downloader("Your Company", "your-email@example.com")

# Download Apple's latest 5 10-K filings
dl.get("10-K", "AAPL", amount=5)

# Download multiple companies' SEC filings
companies = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
for ticker in companies:
    dl.get("10-K", ticker, amount=3)
```

## 📊 Advanced Features: Beyond Basic SEC Downloads

### 1. Company Facts API Integration

Extract structured financial data directly from the SEC EDGAR database:

```
# Get comprehensive company facts including revenue, assets, liabilities
company_data = get_company_facts("AAPL")
# Returns detailed financial metrics from 10-K filings
```

### 2. Batch Processing Multiple Companies

```
# Download SEC filings for 50+ companies simultaneously
results = download_multiple_companies(
    ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "JPM", "V", "JNJ"],
    filings_per_company=10,
    download_filings=True,
    download_facts=True
)
```

### 3. Custom Date Range Filtering

```
# Download SEC filings from specific periods
dl.get("10-K", "AAPL", before_date="2023-12-31", after_date="2020-01-01")
# Perfect for historical analysis and trend identification
```

## 🎯 Real-World Applications

### Investment Research

Use this SEC EDGAR toolkit to conduct deep financial analysis like our AI-driven examination of Apple stock: [Was Apple Stock a Smart Buy in Late 2023? AI Analysis Reveals.](https://funaibuddy.com/was-apple-stock-a-smart-buy-in-late-2023-ai-analysis-reveals/) The analysis reveals how SEC filing data combined with AI financial analysis can uncover investment opportunities.

### Quantitative Analysis

```
# Example: Calculate financial ratios from SEC data
def analyze_financial_ratios(ticker):
    filings = get_10k_filings(ticker, 5)
    facts = get_company_facts(ticker)
    
    # Calculate key metrics from SEC filings
    revenue_growth = calculate_growth(facts, 'Revenues')
    profit_margins = calculate_margins(facts, 'NetIncomeLoss')
    return_metrics = {
        'revenue_growth': revenue_growth,
        'profit_margins': profit_margins
    }
```

### Risk Management & Compliance

Monitor SEC filing compliance, track financial reporting changes, and identify regulatory risks through automated SEC data collection.

## 🔗 Integration with AI Financial Analysis

This SEC EDGAR API toolkit pairs perfectly with AI-powered financial analysis tools. As discussed in our blog post about [The Rise of AI Copilots in Finance](https://funaibuddy.com/the-rise-of-ai-copilots-in-finance-openai-leads-the-way/), combining SEC filing data with AI analysis creates powerful insights for:

* Real-time investment suggestions based on SEC filings
* Automated risk assessment from 10-K disclosures
* Predictive analytics using historical SEC data
* Sentiment analysis of management discussions in 10-K filings

## 🛠️ Installation & Setup Details

```
# Core packages for SEC EDGAR access
pip install sec-api
pip install sec-edgar-downloader
pip install requests
pip install beautifulsoup4
pip install pandas
```

## Configuration

```
# Set your SEC API key (optional but recommended for heavy use)
SEC_API_KEY = "your_sec_api_key_here"

# Configure user agent (REQUIRED for SEC compliance)
USER_AGENT = "Your Name/Company your-email@example.com"
```

## 📚 Learning Resources & Further Reading

* [SEC EDGAR API Documentation](https://www.sec.gov/edgar/sec-api-documentation)
* [sec-api.io Official Docs](https://sec-api.io/docs)
* [sec-edgar-downloader Documentation]([https://sec-edgar-downloader.readthedocs.io/](https://sec-edgar-downloader.readthedocs.io/)

## ⚖️ Legal & Compliance

### SEC Data Usage Policy

This toolkit complies with SEC EDGAR access guidelines:

* Respects rate limits (10 requests per second)
* Includes proper User-Agent headers
* Uses data for legitimate research purposes
* Doesn't overwhelm SEC servers

### Data Licensing

* <b>SEC filings</b>: Public domain (no copyright)
* <b>Code</b>: MIT License
* <b>Derivative analyses</b>: Your ownership

<b>Ready to transform your financial analysis with SEC EDGAR data? Star this repository, fork it for your projects, and join the revolution in data-driven investment research! Built with ❤️ by financial data enthusiasts | Part of the [FunAI Buddy ecosystem](https://www.funaibuddy.com)</b>

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=psachdev/sec_data_downloader&type=Date)](https://star-history.com/#psachdev/sec_data_downloader&Date)
