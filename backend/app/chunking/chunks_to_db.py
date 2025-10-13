from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, Distance, VectorParams
from typing import Callable, Optional, Union, List
from pydantic import BaseModel
from qdrant_client.models import PayloadSchemaType
import os
from dotenv import load_dotenv

load_dotenv()
CHUNKS_COLLECTION_NAME = os.getenv("CHUNKS_COLLECTION_NAME", "demo_chunks")
CONTRACTS_COLLECTION_NAME = os.getenv("CONTRACTS_COLLECTION_NAME", "demo_contracts")
REPOS_COLLECTION_NAME = os.getenv("REPOS_COLLECTION_NAME", "demo_repos")

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

COLLECTION_DIMENSIONS = {
    CHUNKS_COLLECTION_NAME: 1536,      # OpenAI ada-002 for code chunks
    CONTRACTS_COLLECTION_NAME: 1,
    REPOS_COLLECTION_NAME: 1,
}
DEFAULT_EMBEDDING_DIM = 1536

client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY
)

def insert_to_qdrant(
    obj: BaseModel,
    collection_name: str,
    embedding_fn: Optional[Callable[[str], List[float]]] = None
):
    """
    Inserts a WorkingRepo, WorkingContract, or WorkingChunk into Qdrant.
    Automatically creates collection if it doesn't exist.

    Parameters:
    - obj: Pydantic model instance (must have one of: repo_id, contract_id, chunk_id)
    - collection_name: Qdrant collection to insert into
    - embedding_fn: Optional callable to embed source_code into a vector
    """

    payload = obj.model_dump()

    object_id = (
        payload.get("chunk_id") or 
        payload.get("contract_id") or
        payload.get("repo_id")
        
    )
    if object_id is None:
        raise ValueError("Object must have repo_id, contract_id, or chunk_id")

    # print(f"DEBUG: Inserting {collection_name} with ID: {object_id}")
    # print(f"DEBUG: Object type: {type(obj).__name__}")

    text_to_embed = payload.get("source_code")
    if embedding_fn and text_to_embed:
        # print(f"DEBUG: Using embedding function for text of length: {len(text_to_embed)}")
        vector = embedding_fn(text_to_embed)
        # print(f"DEBUG: Generated vector of size: {len(vector)}")
    else:
        # print(f"DEBUG: Using fallback vector (no embedding function or no source_code)")
        expected_dim = COLLECTION_DIMENSIONS.get(collection_name, DEFAULT_EMBEDDING_DIM)
        vector = [0.0] * expected_dim  # fallback dummy vector

    # Create collection if not exists
    existing_collections = [col.name for col in client.get_collections().collections]
    if collection_name not in existing_collections:
        # print(f"DEBUG: Creating new collection: {collection_name}")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=len(vector),
                distance=Distance.COSINE
            )
        )
        # Only create chunk_id index for the chunks collection
        if collection_name == CHUNKS_COLLECTION_NAME:
            client.create_payload_index(
                collection_name=collection_name,
                field_name="chunk_id",
                field_schema=PayloadSchemaType.KEYWORD
            )
    

    try:
        client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=str(object_id),
                    vector=vector,
                    payload=payload
                )
            ]
        )
        # print(f"DEBUG: Successfully inserted {collection_name} with ID: {object_id}")
    except Exception as e:
        print(f"DEBUG: Error inserting {collection_name} with ID {object_id}: {e}")
        raise