from sec_api import QueryApi, ExtractorApi
import pandas as pd
import json

# Initialize with your API key (get free key from https://sec-api.io/)
#queryApi = QueryApi(api_key="YOUR_API_KEY_HERE")
queryApi = QueryApi(api_key="55e2210")

# Search for 10-K filings
query = {
    "query": {
        "query_string": {
            "query": "formType:\"10-K\" AND filedAt:[2025-01-01 TO 2025-01-09]"
        }
    },
    "from": "0",
    "size": "10",
    "sort": [{"filedAt": {"order": "desc"}}]
}

response = queryApi.get_filings(query)

# Save the filings
filings = response['filings']
for filing in filings:
    print(f"Company: {filing['companyName']}")
    print(f"Filing Date: {filing['filedAt']}")
    print(f"URL: {filing['linkToFilingDetails']}")
    print("-" * 50)
