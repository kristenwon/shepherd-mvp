from typing import List, Dict, Any, Union
from pydantic import BaseModel, ValidationError
import json

class Contract(BaseModel):
    contract_name: str
    is_deployed: bool
    is_in_scope: bool

# tracks which contracts are IN SCOPE (indicated on page 2 of the frontend)
class ContractsList(BaseModel):
    contracts: List[Contract]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return self.model_dump()
    
    def to_json(self, indent: int = None) -> str:
        """Convert to a JSON string."""
        # Pydantic v2 has this built in as model_dump_json()
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, obj: Union[str, Dict[str, Any]]) -> "ContractsList":
        """Safely parse from a JSON string or a Python dict."""
        try:
            if isinstance(obj, str):
                data = json.loads(obj)
            else:
                data = obj
            return cls.model_validate(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON received: {e}")
        except ValidationError as e:
            raise ValueError(f"Invalid ContractsList schema: {e}")
        

class SavedChunk(BaseModel):
    chunk_name: str
    chunk_type: str
    is_selected: bool

class SavedContract(BaseModel):
    contract_name: str
    chunks: List[SavedChunk]

# Stores all the contracts/chunks in this repository that were selected by the user (for easy chunk selection)
class SavedRepo(BaseModel):
    deployed_contracts: List[SavedContract]
    undeployed_contracts:  List[SavedContract]

    @classmethod
    def from_demo_repo(cls, demo_repo):
        def convert(contracts):
            return [
                SavedContract(
                    contract_name=c.contract_name,
                    chunks=[
                        SavedChunk(
                            chunk_name=ch.name,
                            chunk_type=ch.chunk_type,
                            is_selected=False
                        )
                        for ch in c.chunks
                    ]
                )
                for c in contracts
            ]

        return cls(
            deployed_contracts=convert(demo_repo.deployed_contracts),
            undeployed_contracts=convert(demo_repo.undeployed_contracts),
        )