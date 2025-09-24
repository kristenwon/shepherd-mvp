import os

ETHERSCAN_BASE_URL = "https://api-sepolia.etherscan.io/api"
# ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
ETHERSCAN_API_KEY = "M8IAYBY1RCENJVGZZ7C9UXGMYVTAUYFP8T"
BASE_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
SLITHER_PATH = os.path.join(BASE_DIR, "slither-env", "Scripts", "slither")
print(SLITHER_PATH)
