import json
import os
from pathlib import Path
from typing import Dict, List, Any
from web3 import Web3
from .constants import BASE_DIR
from .models.contract_asset import ContractAsset
import subprocess
from pathlib import Path
from typing import Dict, Any
from .models.scoped_contracts import ContractsList, Contract
import shutil
from eth_utils import to_bytes, keccak


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


def stitch_sources(base: Path, sources: Dict[str, Any], contract_name: str = None) -> str:
    """Get source code for the contract dynamically searching in src and all subdirectories"""

    if not contract_name:
        return "// source not fully resolved"

    print(f"Looking for source file for contract: {contract_name}")

    src_dir = base / "src"
    if not src_dir.exists():
        print(f"⚠️ src directory not found at: {src_dir}")
        return "// source not fully resolved"

    try:
        # Strategy 1: Use ripgrep for fast file searching (checks src/ and all subdirs)
        cmd = ["rg", "--files", "--glob",
               f"**/{contract_name}.sol", str(src_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0 and result.stdout.strip():
            file_paths = result.stdout.strip().split('\n')
            for file_path in file_paths:
                path = Path(file_path)
                if path.exists():
                    content = path.read_text(encoding="utf-8")
                    # Verify the contract is actually defined in this file
                    if f"contract {contract_name}" in content or f"abstract contract {contract_name}" in content:
                        print(f"Found exact match: {path.relative_to(base)}")
                        return content

        # Strategy 2: Search for files containing the contract definition
        cmd = [
            "rg", "-l", f"^\\s*(contract|abstract\\s+contract)\\s+{contract_name}\\b", "--glob", "*.sol", str(src_dir)]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0 and result.stdout.strip():
            file_paths = result.stdout.strip().split('\n')
            if file_paths:
                path = Path(file_paths[0])  # Take first match
                if path.exists():
                    print(
                        f"Found {contract_name} definition in: {path.relative_to(base)}")
                    return path.read_text(encoding="utf-8")

        # Strategy 3: Broader search - any .sol file with contract name in filename
        cmd = ["rg", "--files", "--glob",
               f"**/*{contract_name}*.sol", str(src_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0 and result.stdout.strip():
            file_paths = result.stdout.strip().split('\n')
            for file_path in file_paths:
                path = Path(file_path)
                if path.exists():
                    content = path.read_text(encoding="utf-8")
                    if f"contract {contract_name}" in content or f"abstract contract {contract_name}" in content:
                        print(
                            f"Found {contract_name} in: {path.relative_to(base)}")
                        return content

    except subprocess.TimeoutExpired:
        print(f"⚠️ Search timed out for contract: {contract_name}")
        return stitch_sources_fallback(base, contract_name)
    except FileNotFoundError:
        print("⚠️ ripgrep not found. Using fallback search...")
        return stitch_sources_fallback(base, contract_name)
    except Exception as e:
        print(f"⚠️ Error using ripgrep: {e}")
        return stitch_sources_fallback(base, contract_name)

    # If ripgrep didn't find anything, use fallback
    return stitch_sources_fallback(base, contract_name)


def stitch_sources_fallback(base: Path, contract_name: str) -> str:
    """Python fallback when ripgrep is not available"""

    src_dir = base / "src"
    if not src_dir.exists():
        return "// source not fully resolved"

    print("Using Python fallback search...")

    # First: Check for exact filename match anywhere in src tree
    exact_matches = list(src_dir.glob(f"**/{contract_name}.sol"))
    for sol_file in exact_matches:
        if sol_file.is_file():
            content = sol_file.read_text(encoding="utf-8")
            if f"contract {contract_name}" in content or f"abstract contract {contract_name}" in content:
                print(f"Found exact match: {sol_file.relative_to(base)}")
                return content

    # Second: Search all .sol files for contract definition
    all_sol_files = list(src_dir.glob("**/*.sol"))
    for sol_file in all_sol_files:
        if sol_file.is_file():
            try:
                content = sol_file.read_text(encoding="utf-8")
                # Check for contract definition (including abstract contracts)
                if (f"contract {contract_name} " in content or
                    f"contract {contract_name}{{" in content or
                        f"abstract contract {contract_name}" in content):
                    print(
                        f"Found {contract_name} in: {sol_file.relative_to(base)}")
                    return content
            except Exception as e:
                continue

    # Third: Partial filename match as last resort
    for sol_file in all_sol_files:
        if contract_name.lower() in sol_file.stem.lower():
            try:
                content = sol_file.read_text(encoding="utf-8")
                if f"contract {contract_name}" in content:
                    print(
                        f"Found {contract_name} in: {sol_file.relative_to(base)}")
                    return content
            except Exception as e:
                continue

    print(f"⚠️ Could not find source file for contract: {contract_name}")

    # Debug: Show what files are available
    if all_sol_files:
        print(f"Available .sol files in src/:")
        for f in all_sol_files[:10]:
            print(f"  - {f.relative_to(base)}")
        if len(all_sol_files) > 10:
            print(f"  ... and {len(all_sol_files) - 10} more files")

    return "// source not fully resolved"


def build_contract_assets_to_mas(input_dir: str, output_dir: str, repo_name: str, tunnel_url: str, contract_list: ContractsList) -> Path:
    """Modified version that saves to specified output directory"""
    base = Path(input_dir)
    repo_path = Path(output_dir)
    repo_path.mkdir(parents=True, exist_ok=True)

    # 1) load artifacts (Foundry)
    artifacts = load_foundry_artifacts(base)

    # 2) discover addresses
    targets = {}  # {label -> address}
    broadcast_dir = base / "broadcast"

    # Look for run-latest.json in broadcast/*/31337/
    deployed_contract_name_list = []
    for run_latest_file in broadcast_dir.rglob("*/31337/run-latest.json"):
        with open(run_latest_file, 'r') as f:
            broadcast_data = json.load(f)

        for tx in broadcast_data.get("transactions", []):
            contract_name = tx.get("contractName")
            contract_address = tx.get("contractAddress")

            # get the hashed creation bytecode to improve matching accuracy (Keccak256 hash)
            creation_bytecode = tx["transaction"]["input"]
            bytecode_bytes = to_bytes(hexstr=creation_bytecode)
            bytecode_hash_run_latest = keccak(bytecode_bytes).hex()

            if contract_name is None:
                print(
                    f"contractname is null for transaction with address: {contract_address}")
                continue
            if contract_name and contract_address:
                targets[contract_name] = (contract_address, bytecode_hash_run_latest)
                deployed_contract_name_list.append(contract_name)

        # 2.5) Write non-deployed-contract-in-scope.json summary in repo_path
        non_deployed_contracts_in_scope = []
        for contract in contract_list.contracts:
            full_name = contract.contract_name
            print(f'full_name -----: {full_name}')
            if not contract.is_deployed and contract.is_in_scope:
                # Normalize to base name for comparison (e.g. "Lender.sol" -> "Lender")
                base_name = full_name.rsplit(".", 1)[0]
                print(f"Checking non-deployed in-scope contract: {base_name}")
                print(f'contract -----: {contract}')
                if base_name not in deployed_contract_name_list:
                    non_deployed_contracts_in_scope.append(
                        {
                            "contract_name": full_name,
                            "is_deployed": contract.is_deployed,
                            "is_in_scope": contract.is_in_scope,
                        }
                    )

        non_deployed_path = repo_path / "non-deployed-contract-in-scope.json"
        non_deployed_path.write_text(
            json.dumps(
                {"contracts": non_deployed_contracts_in_scope}, indent=4),
            encoding="utf-8",
        )
        print(
            f"Created non_deployed_contracts_in_scope file: {non_deployed_path}")

    # 3) match deployed contracts to artifacts
    for label, (addr, bytecode_hash_run_latest) in targets.items():

        # Try to match by contract creation bytecode first
        art = None
        for artifact in artifacts:
            bytecode_out = artifact["creation"].lstrip("0x")
            bytecode_bytes_out = to_bytes(hexstr=bytecode_out)
            bytecode_hash_out = keccak(bytecode_bytes_out).hex()
            
            if bytecode_hash_run_latest == bytecode_hash_out:
                art = artifact
                break

        if not art:
            # if we never get a bytecode match, fallback to contract name matching
            for artifact in artifacts:
                bytecode_out = artifact["creation"]
                
                if artifact["contract_name"] == label:
                    art = artifact
                    break

        if not art:
            print(f"No artifact found with name {label}")
            continue

        # Pass the contract name to stitch_sources
        source_text = stitch_sources(base, art["sources"], contract_name=label)

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

        src_in = base / "src"
        src_out = repo_path / "src"

        if src_in.exists() and src_in.is_dir():
            # Remove existing destination folder so copytree won't raise
            if src_out.exists():
                shutil.rmtree(src_out)

            shutil.copytree(src_in, src_out)
            print(f"Copied src directory from {src_in} → {src_out}")
        else:
            print(f"No src folder found at: {src_in}")

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
