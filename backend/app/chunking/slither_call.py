# i need to pass a list of these chunks to the external fastapi service that is another repository
from typing import List, Dict
import requests
import os
import json
from .workingChunkModels import WorkingChunk, SlitherChunk, WorkingContract

# Configure the Slither analyzer service URL
SLITHER_SERVICE_URL = os.getenv(
    "SLITHER_SERVICE_URL", "http://localhost:8002/analyze")
MYTHRIL_SERVICE_URL = os.getenv(
    "MYTHRIL_SERVICE_URL", "http://localhost:8001/analyze-contract")
MYTHRIL_UPDATE_VOLUME_URL = os.getenv(
    "MYTHRIL_UPDATE_VOLUME_URL", "http://localhost:8001/update-volume")
MYTHRIL_CLEAR_VOLUME_URL = os.getenv(
    "MYTHRIL_CLEAR_VOLUME_URL", "http://localhost:8001/clear-volume")


def analyze_chunks_with_slither(slither_chunks: List[SlitherChunk], repo_url: str, contract_id_to_name: Dict[str, str]):
    """
    Send slither chunks to the slither analyzer service
    """

    # Prepare the payload
    payload = {
        "repo_url": repo_url,
        "chunks": [chunk.model_dump() for chunk in slither_chunks],
        "contract_names": contract_id_to_name
    }

    # Make request to slither analyzer service
    response = requests.post(SLITHER_SERVICE_URL, json=payload)

    # Check if request was successful
    response.raise_for_status()

    # Return the analysis results
    return response.json()


def analyze_chunks_with_mythril(mythril_chunks: List[SlitherChunk], source_code: str, contract_name: str, contract_id: str):
    """
    Call the mythril analyzer service on a contract's source code
    """

    # create dictionary of {id : name} to keep consistent with slither form
    contract_names = {
        # only contains one element, since we are analyzing one contract
        contract_id: contract_name
    }

    # Prepare the payload
    payload = {
        'contract_code': source_code,
        'contract_name': contract_name,
        'contract_names': contract_names,
        'chunks': [chunk.model_dump() for chunk in mythril_chunks],
        'solc_version': "0.8.19",  # Match the default
        'analysis_mode': "quick",  # Match the default
        'max_depth': 22,           # Match the default
        'execution_timeout': 300   # Match the default
    }

    # Make request to mythril analyzer service
    response = requests.post(
        MYTHRIL_SERVICE_URL,
        json=payload,
        timeout=360
    )

    if response.status_code == 200:
        result = response.json()
        print(f"Mythril analysis completed for {contract_name}")
        # print(f"Updated {result.get('chunks_updated', 0)} chunks with Mythril findings")

        if result.get('success'):
            analysis_data = result.get('analysis_result', {})
            issues = analysis_data.get('issues', [])
            print(issues)

            return {
                'success': True,
                'contract_name': contract_name,
                'issues': issues,
                'chunks_updated': result.get('chunks_updated', 0),
                'summary': analysis_data.get('summary', {}),
                'analysis_id': analysis_data.get('analysis_id')
            }
        else:
            print(f"Mythril analysis failed: {result.get('error')}")
            return {
                'success': False,
                'error': result.get('error'),
                'contract_name': contract_name,
                'issues': []
            }
    else:
        print(f"HTTP Error: {response.status_code}")
        print(f"Response: {response.text}")
        response.raise_for_status()

    # Return the analysis results
    return response.json()


def update_mythril_shared_volume(contracts: List[WorkingContract]):
    """Update the mythril shared volume with the source code of all contracts"""
    name_to_source_code = {}
    for contract in contracts:
        # Use filename that matches import statements
        filename = f"{contract.contract_name}.sol" if not contract.contract_name.endswith(
            '.sol') else contract.contract_name
        name_to_source_code[filename] = contract.source_code

    payload = {'name_to_source_code': name_to_source_code}
    response = requests.post(MYTHRIL_UPDATE_VOLUME_URL, json=payload)
    response.raise_for_status()
    return response.json()


def clear_mythril_shared_volume():
    """
    Clear the mythril shared volume
    """
    # Make request to mythril shared volume service
    response = requests.post(MYTHRIL_CLEAR_VOLUME_URL)
    response.raise_for_status()
    return response.json()
