import json
import os
from pathlib import Path
from typing import Dict, List, Any
from web3 import Web3
from .constants import BASE_DIR
from .models.contract_asset import ContractAsset


def load_foundry_artifacts(base: Path) -> List[Dict[str, Any]]:
    """Load Foundry artifacts from out/ directory
    """
    artifacts = []
    out_dir = base / "out"

    # Foundry structure: out/ContractName.sol/ContractName.json
    for sol_dir in out_dir.glob("*.sol"):
        if sol_dir.is_dir():
            for json_file in sol_dir.glob("*.json"):
                with open(json_file, 'r') as f:
                    artifact_data = json.load(f)

                artifacts.append({
                    "contract_name": json_file.stem,
                    "abi": artifact_data["abi"],
                    "creation": artifact_data["bytecode"]["object"],
                    "deployed": artifact_data["deployedBytecode"]["object"],
                    "sources": artifact_data.get("metadata", {}).get("sources", {})
                })

    return artifacts


def stitch_sources(base: Path, sources: Dict[str, Any]) -> str:
    """Get source code for just the main contract file"""

    # Find source files that look like main contracts (in src/)
    for file_path, file_data in sources.items():
        if file_path.startswith("src/") and file_path.endswith(".sol"):
            print(f"Found source file: {file_path}")

            full_path = base / file_path
            if full_path.exists():
                print(f"Reading from: {full_path}")
                return full_path.read_text(encoding="utf-8")
            else:
                print(f"Warning: File not found at {full_path}")

    return "// source not fully resolved"


def build_contract_assets_to_mas(input_dir: str, output_dir: str, repo_name: str, tunnel_url: str):
    """Modified version that saves to specified output directory"""
    base = Path(input_dir)
    repo_path = Path(output_dir)  # Use the provided MAS deployments path
    repo_path.mkdir(parents=True, exist_ok=True)
    contract_assets: List[ContractAsset] = []

    # 1) load artifacts (Foundry)
    artifacts = load_foundry_artifacts(base)

    # 2) discover addresses
    targets = {}  # {label -> address}
    broadcast_dir = base / "broadcast"

    # Look for run-latest.json in broadcast/*/31337/
    for run_latest_file in broadcast_dir.rglob("*/31337/run-latest.json"):
        with open(run_latest_file, 'r') as f:
            broadcast_data = json.load(f)

        for tx in broadcast_data.get("transactions", []):
            if tx.get("transactionType") == "CREATE":
                contract_name = tx.get("contractName")
                contract_address = tx.get("contractAddress")
                if contract_name and contract_address:
                    targets[contract_name] = contract_address

    # 3) match deployed contracts to artifacts

    for label, addr in targets.items():

        # Match by contract name instead of bytecode
        art = None
        for artifact in artifacts:
            if artifact["contract_name"] == label:
                art = artifact
                break

        if not art:
            print(f"No artifact found with name {label}")
            continue

        source_text = stitch_sources(base, art["sources"])

        asset = {
            "contract_name": label,
            "abi": art["abi"],
            "bytecode": "0x" + art["creation"].lstrip("0x"),
            "source_code": source_text or "// source not fully resolved",
            "deployed_address": Web3.to_checksum_address(addr),
            "network_url": tunnel_url
        }

        short = addr[:6] + "…" + addr[-4:]
        output_file = repo_path / f"{asset['contract_name']}_{short}.json"
        output_file.write_text(json.dumps(asset, indent=2), encoding="utf-8")

        print(f"Created asset: {output_file}")
    return repo_path


def load_contract_assets_from_deployments(repo_name: str):
    """
    Load contract assets that were saved by shepherd-mvp in deployments folder

    Args:
        repo_name: Name of the repository (folder name in deployments)

    Returns:
        tuple: (repo_path, contract_assets)
    """
    repo_path = Path(BASE_DIR) / "deployments" / repo_name
    contract_assets = []

    if not repo_path.exists():
        raise ValueError(f"Deployments folder not found: {repo_path}")

    # Load all JSON files from the deployments directory
    json_files = list(repo_path.glob("*.json"))

    if not json_files:
        raise ValueError(f"No contract assets found in: {repo_path}")

    for json_file in json_files:
        with open(json_file, 'r') as f:
            asset = json.load(f)
            contract_assets.append(asset)

    print(f"📦 Loaded {len(contract_assets)} contract assets from {repo_path}")

    return repo_path, contract_assets
