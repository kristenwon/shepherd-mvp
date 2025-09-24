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

            full_path = base / file_path
            if full_path.exists():
                print(f"Reading from: {full_path}")
                return full_path.read_text(encoding="utf-8")
            else:
                print(f"Warning: File not found at {full_path}")

    return "// source not fully resolved"


def build_contract_assets_to_mas(input_dir: str, output_dir: str, repo_name: str) -> List[Dict[str, Any]]:
    """Modified version that saves to specified output directory"""
    base = Path(input_dir)
    repo_path = Path(output_dir)  # Use the provided MAS deployments path
    repo_path.mkdir(parents=True, exist_ok=True)
    contract_assets = []

    # 1) load artifacts (Foundry)
    artifacts = load_foundry_artifacts(base)

    # 2) discover addresses
    targets = {}
    broadcast_dir = base / "broadcast"

    for run_latest_file in broadcast_dir.rglob("*/31337/run-latest.json"):
        with open(run_latest_file, 'r') as f:
            broadcast_data = json.load(f)

        for tx in broadcast_data.get("transactions", []):
            if tx.get("transactionType") == "CREATE":
                contract_name = tx.get("contractName")
                contract_address = tx.get("contractAddress")
                if contract_name and contract_address:
                    targets[contract_name] = contract_address

    # 3) match and save to MAS deployments
    for label, addr in targets.items():
        art = None
        for artifact in artifacts:
            if artifact["contract_name"] == label:
                art = artifact
                break

        if not art:
            continue

        source_text = stitch_sources(base, art["sources"])

        asset = {
            "contract_name": label,
            "abi": art["abi"],
            "bytecode": "0x" + art["creation"].lstrip("0x"),
            "source_code": source_text or "// source not fully resolved",
            "deployed_address": Web3.to_checksum_address(addr),
            "network_url": "http://127.0.0.1:8545"
        }

        short = addr[:6] + "…" + addr[-4:]
        output_file = repo_path / f"{asset['contract_name']}_{short}.json"
        output_file.write_text(json.dumps(asset, indent=2), encoding="utf-8")

        print(f"Created asset in MAS: {output_file}")
        contract_assets.append(asset)

    return contract_assets


# Should contain out/, broadcast/, src/
TEST_INPUT_DIR = Path(__file__).parent.parent / "uploads"
TEST_REPO_NAME = "my-assets"
# TEST_RPC_URL = "http://127.0.0.1:8545"


def test_basic():
    # Add debugging to see what's happening
    test_dir = Path("/Users/chachachoco/shepherd-mvp/uploads/my-assets")

    print(f"Looking in: {test_dir}")
    print(f"Directory exists: {test_dir.exists()}")

    if test_dir.exists():
        print(f"Contents: {list(test_dir.iterdir())}")

        out_dir = test_dir / "out"
        print(f"out/ exists: {out_dir.exists()}")
        if out_dir.exists():
            print(f"out/ contents: {list(out_dir.iterdir())}")

        broadcast_dir = test_dir / "broadcast"
        print(f"broadcast/ exists: {broadcast_dir.exists()}")
        if broadcast_dir.exists():
            print(
                f"broadcast/ contents: {list(broadcast_dir.rglob('*.json'))}")

    # Run the builder
    repo_path, contract_assets = build_contract_assets(
        str(test_dir), TEST_REPO_NAME)

    print(f"Found {len(contract_assets)} contracts")

    # Check deployments folder was created
    deployments_dir = Path(BASE_DIR) / "deployments" / TEST_REPO_NAME
    assert deployments_dir.exists(), "Deployments directory not created"

    # Check that JSON files were created
    json_files = list(deployments_dir.glob("*.json"))

    if len(json_files) == 0:
        print("No assets created because:")
        print("- No artifacts found in out/")
        print("- Or no deployed contracts found in broadcast/")
        print("- Or no matching between artifacts and deployments")
        return

    assert len(json_files) > 0, "No asset files created"

    # Verify basic structure of first asset
    with open(json_files[0], 'r') as f:
        asset = json.load(f)

    required_fields = ["contract_name", "abi",
                       "bytecode", "source_code", "deployed_address"]
    for field in required_fields:
        assert field in asset, f"Missing field: {field}"

    print(f"✓ Created {len(json_files)} asset(s)")
    print(
        f"✓ First asset: {asset['contract_name']} at {asset['deployed_address']}")


if __name__ == "__main__":
    test_basic()
