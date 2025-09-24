from pydantic import BaseModel
from typing import List

class ContractAsset(BaseModel):
    contract_name: str
    abi: List[dict]
    bytecode: str
    source_code: str
    deployed_address: str
    network_url: str


