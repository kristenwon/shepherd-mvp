from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Json, Field
from datetime import datetime, date
from typing import Any, List, Optional


class WorkingChunkMetadata(BaseModel):
    """Solidity-specific metadata for chunks"""
    descriptive_id: str
    visibility: Optional[str] = None
    mutability: Optional[str] = None
    modifier_list: List[str] = Field(default_factory=list)
    parameters: List[Dict[str, str]] = Field(default_factory=list)
    return_type: Optional[str] = None

    # Source tracking
    source_file: Optional[str] = None
    file_path: Optional[str] = None


class SlitherChunk(BaseModel):
    """Condensed chunk version to pass to Slither"""
    chunk_id: str                    # UUID
    name: str
    contract_id: str                 # UUID
    start_line: int
    end_line: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return self.model_dump()


class WorkingChunk(BaseModel):
    """Individual code chunk (function, modifier, event, etc.)"""
    chunk_id: str                    # UUID
    contract_id: str                 # UUID
    # function_definition, modifier_definition, etc.
    chunk_type: str
    name: str
    start_line: int
    end_line: int
    source_code: str
    metadata: WorkingChunkMetadata   # Structured Solidity metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return self.model_dump()

    def to_slither_chunk(self) -> SlitherChunk:
        return SlitherChunk(
            chunk_id=self.chunk_id,
            name=self.name,
            contract_id=self.contract_id,
            start_line=self.start_line,
            end_line=self.end_line
        )


class WorkingContract(BaseModel):
    """Solidity contract containing multiple chunks"""
    contract_id: str                 # UUID
    repo_id: str                     # UUID
    contract_name: str
    start_line: int
    end_line: int
    source_code: str                 # Full contract source
    # Functions, modifiers, events, etc.
    chunks: List[WorkingChunk]
    metadata: Dict[str, Any] = Field(
        default_factory=dict)  # Contract-level metadata

    # Convenience methods
    def get_functions(self) -> List[WorkingChunk]:
        return [c for c in self.chunks if c.chunk_type == 'function_definition']

    def get_events(self) -> List[WorkingChunk]:
        return [c for c in self.chunks if c.chunk_type == 'event_definition']

    def get_modifiers(self) -> List[WorkingChunk]:
        return [c for c in self.chunks if c.chunk_type == 'modifier_definition']


class WorkingRepo(BaseModel):
    """Repository containing multiple contracts"""
    repo_id: str                     # UUID
    name: str
    url: str
    contracts: List[WorkingContract]
    commit_hash: Optional[str]
    whitepaper: Optional[str]
    metadata: Dict[str, Any] = Field(
        default_factory=dict)  # Repo-level metadata
    created_at: datetime

    # Convenience methods
    def get_all_chunks(self) -> List[WorkingChunk]:
        """Get all chunks across all contracts"""
        all_chunks = []
        for contract in self.contracts:
            all_chunks.extend(contract.chunks)
        return all_chunks

    def get_contract_by_name(self, name: str) -> Optional[WorkingContract]:
        return next((c for c in self.contracts if c.contract_name == name), None)

    def get_chunk_count(self) -> int:
        return sum(len(c.chunks) for c in self.contracts)


class SlitherContract(BaseModel):
    """Condensed contract version to pass to Slither"""
    contract_id: str                 # UUID
    # Functions, modifiers, events, etc.
    chunks: List[SlitherChunk]


class SlitherRepo(BaseModel):
    """Condensed repo version to pass to Slither"""
    contracts: List[SlitherContract]

    def get_chunk_count(self) -> int:
        return sum(len(c.chunks) for c in self.contracts)
