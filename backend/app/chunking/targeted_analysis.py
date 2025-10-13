"""
Targeted Vulnerability Analysis Functions

This module provides functions for hypothesis-driven smart contract vulnerability analysis,
including user input collection, Qdrant querying, and similarity search for POCs.
"""

from qdrant_client.http.models import Filter, FieldCondition, MatchValue, PointStruct, Distance, VectorParams
from qdrant_client import QdrantClient
from qdrant_client.models import PayloadSchemaType
from typing import Dict, List, Any
import os
import json
import logging
from dotenv import load_dotenv
from ..llms import create_openai_embeddings

load_dotenv()

# Suppress verbose logging from httpx (used by Qdrant and OpenAI)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Qdrant setup
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

qdrant_client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY
)

# OpenAI embeddings for similarity search
embeddings = create_openai_embeddings()


def get_embedding(text: str) -> list:
    """Generate embeddings using OpenAI."""
    return embeddings.embed_documents([text])[0]


def ensure_required_indexes():
    """
    Create required indexes for filtering operations.
    This should be called before attempting to query.
    """
    try:
        # Create index for contract_name in working_contracts collection
        qdrant_client.create_payload_index(
            collection_name=os.getenv(
                "CONTRACTS_COLLECTION_NAME", "demo_contracts"),
            field_name="contract_name",
            field_schema=PayloadSchemaType.KEYWORD
        )

        # Create index for contract_id in working_chunks collection
        qdrant_client.create_payload_index(
            collection_name=os.getenv("CHUNKS_COLLECTION_NAME", "demo_chunks"),
            field_name="contract_id",
            field_schema=PayloadSchemaType.KEYWORD
        )

        # Create index for name (chunk name) in working_chunks collection
        qdrant_client.create_payload_index(
            collection_name=os.getenv("CHUNKS_COLLECTION_NAME", "demo_chunks"),
            field_name="name",
            field_schema=PayloadSchemaType.KEYWORD
        )
    except Exception as e:
        # Indexes might already exist, that's fine
        pass


def fetch_chunk(contract_name: str, chunk_name: str) -> dict:
    """
    Fetch chunk metadata by contract name and chunk name.
    First queries working_contracts to get contract_id, then queries working_chunks.
    """
    from api.agents.tagged_output import TaggedOutput

    try:
        # Ensure required indexes exist
        ensure_required_indexes()

        # Step 1: Get contract_id from contract_name
        contract_filter = Filter(
            must=[
                FieldCondition(key="contract_name",
                               match=MatchValue(value=contract_name))
            ]
        )

        contract_result = qdrant_client.scroll(
            collection_name=os.getenv(
                "CONTRACTS_COLLECTION_NAME", "demo_contracts"),
            scroll_filter=contract_filter,
            limit=1
        )

        contract_points = contract_result[0]
        if not contract_points:
            TaggedOutput.description(
                f"No contract found with name: {contract_name}")
            return {}

        contract_id = contract_points[0].payload.get("contract_id")
        if not contract_id:
            TaggedOutput.description(
                "Contract found but no contract_id in payload")
            return {}

        TaggedOutput.description(
            f"Found contract '{contract_name}' with ID: {contract_id}")

        # Step 2: Get chunk using contract_id and chunk name
        chunk_filter = Filter(
            must=[
                FieldCondition(key="contract_id",
                               match=MatchValue(value=contract_id)),
                FieldCondition(key="name", match=MatchValue(value=chunk_name))
            ]
        )

        chunk_result = qdrant_client.scroll(
            collection_name=os.getenv("CHUNKS_COLLECTION_NAME", "demo_chunks"),
            scroll_filter=chunk_filter,
            limit=1
        )

        chunk_points = chunk_result[0]
        if not chunk_points:
            TaggedOutput.description(
                f"No chunk found with name '{chunk_name}' in contract '{contract_name}'")
            return {}

        metadata = chunk_points[0].payload
        TaggedOutput.description("COMPLETE CHUNK METADATA")

        # Print the complete payload in a formatted way
        TaggedOutput.description(json.dumps(metadata, indent=2, default=str))

        return metadata

    except Exception as e:
        TaggedOutput.description(f"Error querying Qdrant: {e}")
        return {}


def collect_user_query() -> dict:
    """Collect user input with detailed hypothesis for targeted vulnerability analysis."""
    from api.agents.tagged_output import TaggedOutput
    from api.chunking.token_utils import create_token_counter
    from api.chunking.targeted_analysis import fetch_chunk

    # TaggedOutput.description("DETAILED VULNERABILITY HYPOTHESIS ANALYSIS")

    # Initialize token counter for o3-mini (the planner model)
    token_counter = create_token_counter("o3-mini")
    recommended_limit = token_counter.get_recommended_limit(
        reserve_for_response=0.3)  # Reserve 30% for response

    # Store multiple contract/chunk pairs
    contract_chunks = []
    total_tokens = 0

    print(
        f"Token Management: Using {token_counter.model_name} with {token_counter.get_context_limit():,} token limit")
    print(
        f"Recommended input limit: {recommended_limit:,} tokens (reserving 30% for response)")
    print(f"Current usage: {total_tokens:,} tokens")

    # Get hypothesis first (doesn't count much toward token limit)
    TaggedOutput.user_input(
        "Enter your detailed vulnerability hypothesis")

    hypothesis_lines = []
    while True:
        line = input()
        if line == "" and hypothesis_lines:  # Empty line and we have content
            break
        elif line != "":  # Non-empty line
            hypothesis_lines.append(line)

    hypothesis = " ".join(hypothesis_lines).strip()
    TaggedOutput.user_input(
        "Enter your detailed vulnerability hypothesis", hypothesis)

    # Add hypothesis to token count
    total_tokens += token_counter.count_tokens(hypothesis)

    # Collect multiple contract/chunk pairs
    while True:
        TaggedOutput.description(f"CONTRACT/CHUNK {len(contract_chunks) + 1}")

        TaggedOutput.user_input(
            "Enter the contract name (e.g., Vault, BuyPurpose): ")
        contract_name = input(
            "Enter the contract name (e.g., Vault, BuyPurpose): ").strip()

        if not contract_name:
            TaggedOutput.description(
                "Contract name cannot be empty. Skipping...")
            continue

        TaggedOutput.user_input(
            "Enter the contract name (e.g., Vault, BuyPurpose): ", contract_name)

        TaggedOutput.user_input(
            "Enter the specific function or area (e.g., withdraw, constructor): ")
        chunk_name = input(
            "Enter the specific function or area (e.g., withdraw, constructor): ").strip()

        if not chunk_name:
            TaggedOutput.description("Chunk name cannot be empty. Skipping...")
            continue

        TaggedOutput.user_input(
            "Enter the specific function or area (e.g., withdraw, constructor): ", chunk_name)

        # Try to fetch the chunk to estimate token usage
        try:
            chunk_data = fetch_chunk(contract_name, chunk_name)
            if chunk_data and chunk_data.get("source_code"):
                estimated_tokens = token_counter.estimate_chunk_tokens(
                    chunk_data)

                print(
                    f"📊 Token Estimation for {contract_name}.{chunk_name}:\n"
                    f"   Estimated tokens: {estimated_tokens:,}\n"
                    f"   Current total: {total_tokens:,} tokens\n"
                    f"   After adding: {total_tokens + estimated_tokens:,} tokens"
                )

                # Check if adding this chunk would exceed limits
                if total_tokens + estimated_tokens > recommended_limit:
                    TaggedOutput.description(
                        f"⚠️  WARNING: Adding this chunk would exceed the recommended limit!\n"
                        f"   Recommended limit: {recommended_limit:,} tokens\n"
                        f"   Would reach: {total_tokens + estimated_tokens:,} tokens"
                    )

                    TaggedOutput.user_input(
                        "Do you want to add it anyway? (y/n): ")
                    choice = input(
                        "\nDo you want to add it anyway? (y/n): ").strip().lower()
                    TaggedOutput.user_input(
                        "Do you want to add it anyway? (y/n): ", choice)
                    if choice != 'y':
                        TaggedOutput.description("Skipping this chunk...")
                        continue

                # Add the contract/chunk pair
                contract_chunks.append({
                    "contract_name": contract_name,
                    "chunk_name": chunk_name,
                    "estimated_tokens": estimated_tokens
                })

                total_tokens += estimated_tokens

                print(
                    f"✅ Added {contract_name}.{chunk_name} ({estimated_tokens:,} tokens)")
                print(
                    f"📈 Total tokens so far: {total_tokens:,} tokens")

            else:
                TaggedOutput.description(
                    f"⚠️  Warning: Could not fetch chunk data for {contract_name}.{chunk_name}")
                print("Adding without token estimation...")

                # Add with default token estimate
                default_estimate = 1000  # Conservative estimate
                contract_chunks.append({
                    "contract_name": contract_name,
                    "chunk_name": chunk_name,
                    "estimated_tokens": default_estimate
                })
                total_tokens += default_estimate

        except Exception as e:
            TaggedOutput.description(f"⚠️  Error fetching chunk data: {e}")
            TaggedOutput.description("Adding without token estimation...")

            # Add with default token estimate
            default_estimate = 1000
            contract_chunks.append({
                "contract_name": contract_name,
                "chunk_name": chunk_name,
                "estimated_tokens": default_estimate
            })
            total_tokens += default_estimate

        # Ask if user wants to add more
        TaggedOutput.description(
            f"{token_counter.format_token_usage(total_tokens)}")

        if total_tokens >= recommended_limit:
            TaggedOutput.description(
                f"🛑 You've reached the recommended token limit ({recommended_limit:,} tokens)")
            TaggedOutput.description(
                "Consider stopping here to ensure the planner has enough context space.")

        TaggedOutput.user_input("Add another contract/chunk? (y/n): ")
        choice = input("\nAdd another contract/chunk? (y/n): ").strip().lower()
        TaggedOutput.user_input("Add another contract/chunk? (y/n): ", choice)
        if choice != 'y':
            break

    # Final summary
    TaggedOutput.description("FINAL INPUT SUMMARY")
    TaggedOutput.description(f"Detailed Hypothesis: {hypothesis}")
    TaggedOutput.description(
        f"Contracts and Chunks ({len(contract_chunks)} total):")

    for i, item in enumerate(contract_chunks, 1):
        TaggedOutput.description(
            f"  {i}. {item['contract_name']}.{item['chunk_name']} ({item['estimated_tokens']:,} tokens)")

    TaggedOutput.description(
        f"Token Usage Summary:\n"
        f"  Hypothesis: {token_counter.count_tokens(hypothesis):,} tokens\n"
        f"  Contract/Chunk data: {sum(item['estimated_tokens'] for item in contract_chunks):,} tokens\n"
        f"  Total estimated: {total_tokens:,} tokens\n"
        f"  Context limit: {token_counter.get_context_limit():,} tokens\n"
        f"  Usage percentage: {(total_tokens / token_counter.get_context_limit()) * 100:.1f}%"
    )

    if total_tokens > recommended_limit:
        TaggedOutput.description(
            f"⚠️  WARNING: Input exceeds recommended limit by {total_tokens - recommended_limit:,} tokens\n"
            f"This may reduce the planner's ability to generate comprehensive responses."
        )

    return {
        "detailed_hypothesis": hypothesis,
        "contract_chunks": contract_chunks,
        "total_estimated_tokens": total_tokens,
        "token_usage_percentage": (total_tokens / token_counter.get_context_limit()) * 100
    }


def search_similar_pocs(hypothesis: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Search for similar findings using pure cosine similarity search.

    Args:
        hypothesis: User's detailed vulnerability hypothesis
        top_k: Number of results to return

    Returns:
        List of top-k most similar findings with complete payloads
    """
    try:
        # Generate embedding for the hypothesis
        query_vector = get_embedding(hypothesis)

        # Perform pure vector search without any filters
        search_results = qdrant_client.search(
            collection_name="general_2_labeled_findings",
            query_vector=query_vector,
            limit=top_k,
            score_threshold=0.0  # No threshold - get all results
        )

        # Extract complete payloads
        findings = []
        for hit in search_results:
            finding = {
                "similarity_score": hit.score,
                "point_id": hit.id,
                "payload": hit.payload
            }
            findings.append(finding)

        print(f"\n[Cosine Similarity Search Results]")
        print(f"Found {len(findings)} similar findings for hypothesis:")
        print(f"'{hypothesis}'\n")

        for i, finding in enumerate(findings, 1):
            print(f"\n{'='*80}")
            print(
                f"RESULT #{i} - Similarity Score: {finding['similarity_score']:.4f}")
            print(f"Point ID: {finding['point_id']}")
            print('='*80)

            # Print payload in formatted JSON
            payload = finding['payload']
            print("COMPLETE PAYLOAD:")
            print(json.dumps(payload, indent=2, default=str))
            print('='*80)

        return findings

    except Exception as e:
        print(f"Error in cosine similarity search: {e}")
        return []
