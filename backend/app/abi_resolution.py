from typing import List, Dict, Any
from .models.contract_asset import ContractAsset
from eth_utils import to_bytes, keccak
from web3 import Web3



def resolve_abi(assets: List[ContractAsset], artifacts: List[Dict[str, Any]]) -> List[ContractAsset]:
    """
    Resolve the ABI for a list of contract assets that may contian proxies.

    This function:
        - If not proxy → return unchanged
        - Else → map impl_address → contract_name via run-latest
        - Look up ABI for that contract_name using get_abi()
        - Update c['abi'] and optionally c['implementation_contract_name']
    """

    # 2. build deployment_map
    deployment_map = { asset["deployed_address"].lower(): asset for asset in assets }

    w3 = Web3(Web3.HTTPProvider(RPC_URL))

    for c in assets:
        # --- Not a proxy, return the original contract asset ---------------------------------------
        if not c.get("is_proxy", False):
            continue

        proxy_type = c.get("proxy_type")
        impl_address = c.get("impl_address")
        contract_name = c.get("contract_name")
        if not impl_address:
            continue
        impl_address = impl_address.lower()

        # direct lookup: search for the implementation address in our existing contract assets -> return ABI
        # here we search in /out by CREATION bytecode
        asset = deployment_map.get(impl_address)
        if asset:
            creation_bytecode = asset.get("bytecode")
            if creation_bytecode:
                # --- Fetch ABI -------------------------------------------------------
                try:
                    creation_bytecode_hash = hash_bytecode(creation_bytecode)
                    new_abi = get_abi(contract_name, creation_bytecode_hash, artifacts, creation_bytecode = True)
                    c["impl_abi"] = new_abi
                    continue

                except Exception as e:
                    # continue into fallback defined below
                    pass

        # fallback if searching in contract assets doesn't work
        # get the DEPLOYED bytecode from the chain using eth_getCode
        try:
            impl_checksum = Web3.to_checksum_address(impl_address)
            runtime_bytecode = w3.eth.get_code(impl_checksum)

            if not runtime_bytecode or runtime_bytecode == b"":
                c["abi_resolution_error"] = f"no_code_at_address:{impl_address}"
                continue

            runtime_hash = keccak(runtime_bytecode).hex()
            new_abi = get_abi(contract_name, runtime_hash, artifacts, creation_bytecode = False)

            if not new_abi:
                c["abi_resolution_error"] = f"artifact_not_found_for_runtime:{impl_address}"
                continue

            c["impl_abi"] = new_abi

        except Exception as e:
            c["abi_resolution_error"] = f"eth_getCode_failed:{str(e)}"
            continue

    return assets


def get_abi(contract_name: str, bytecode_hash: str, artifacts: List[Dict[str, Any]], creation_bytecode = True):
    # Match by bytecode hash
    for artifact in artifacts:
        if creation_bytecode:
            bytecode_out = artifact["creation"].lstrip("0x")
        else:
            bytecode_out = artifact["deployed"].lstrip("0x")

        bytecode_hash_out = hash_bytecode(bytecode_out)
        if bytecode_hash == bytecode_hash_out:
            return artifact["abi"]
    
    # if we never get a bytecode match, fallback to contract name matching
    for artifact in artifacts:
        if artifact["contract_name"] == contract_name:
            return artifact["abi"]

    return None

def hash_bytecode(bytecode: str) -> str:
    bytecode_bytes_out = to_bytes(hexstr=bytecode)
    return keccak(bytecode_bytes_out).hex()