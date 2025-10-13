"""
Solidity AST-Based Chunker
Uses tree-sitter for semantic code chunking
Returns hierarchical repo/contract/chunk structure
"""

import tree_sitter_solidity as ts_solidity
from tree_sitter import Language, Parser, Node
import tree_sitter
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel
from pathlib import Path
import json
import uuid
import os
from datetime import datetime
import logging
from ..llms import create_openai_embeddings
from .workingChunkModels import WorkingChunk, WorkingContract, WorkingChunkMetadata, WorkingRepo, SlitherContract, SlitherChunk, SlitherRepo
from .chunks_to_db import insert_to_qdrant
from .slither_call import analyze_chunks_with_mythril, analyze_chunks_with_slither, clear_mythril_shared_volume, update_mythril_shared_volume

# Suppress verbose logging from httpx (used by Qdrant and OpenAI)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("qdrant_client").setLevel(logging.WARNING)

embeddings = create_openai_embeddings()


def get_embedding(text: str) -> list:
    return embeddings.embed_documents([text])[0]


class SolidityChunker:
    """
    AST-based Solidity code chunker using Tree-Sitter
    """

    def __init__(self):
        # Initialize Tree-Sitter parser

        self.language = Language(ts_solidity.language())
        self.parser = Parser(self.language)

        # Define which AST node types should be chunked
        self.chunkable_node_types = {
            'function_definition',
            'modifier_definition',
            'event_definition',
            'struct_declaration',
            'enum_declaration',
            'error_declaration',
            'constructor_definition',
            'state_variable_declaration',
            'fallback_receive_definition'
        }

        self.contract_types = {
            'contract_declaration',
            'interface_declaration',
            'library_declaration'
        }

        # Solidity-specific keywords for metadata extraction
        self.visibility_keywords = {
            'public', 'private', 'internal', 'external'}
        self.mutability_keywords = {'pure', 'view', 'payable', 'nonpayable'}

    # Main function to call to chunk a whole repo
    def parse_project(self, repo_path: str, repo_name: str = None, repo_url: str = "",
                      commit_hash: str = None, whitepaper: str = None, toSlither: bool = False) -> Union[WorkingRepo, SlitherRepo]:
        """
        Parse multiple Solidity contracts from JSON files in a repository
        Handles multiple contracts within the same source file

        If toSlither is true, returns a condensed version (SlitherRepo) of the repo, contracts, and chunks designed to send to Slither
        Else returns a WorkingRepo
        """

        # Validate inputs
        if repo_path == "":
            raise FileNotFoundError(
                f"No solidity source code found in {repo_path}")

        if not os.path.exists(repo_path):
            raise FileNotFoundError(
                f"Repository path does not exist: {repo_path}")

        # Generate repo ID and set defaults
        repo_id = str(uuid.uuid4())
        if repo_name is None:
            repo_name = Path(repo_path).name

        json_files = [f for f in os.listdir(repo_path) if f.endswith(".json")]

        if not json_files:
            raise FileNotFoundError(f"No JSON files found in {repo_path}")

        print(f"Found {len(json_files)} JSON files in {repo_path}")

        all_contracts = []

        for filename in json_files:
            file_path = os.path.join(repo_path, filename)
            print(f"Processing: {filename}")

            try:
                # Load JSON data
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Extract required fields
                primary_contract_name = data["contract_name"]
                source_code = data["source_code"]

                # Parse the source to find all contracts
                tree = self.parser.parse(bytes(source_code, 'utf8'))

                # Find all contract/interface/library declarations
                contract_nodes = []
                for child in tree.root_node.children:
                    if child.type in self.contract_types:  # contract_declaration, interface_declaration, library_declaration
                        contract_nodes.append(child)

                if not contract_nodes:
                    # No contracts found, treat entire source as one contract
                    print(
                        f"    No contract declarations found, treating as single contract: {primary_contract_name}")

                    contract_id = str(uuid.uuid4())
                    chunks = self._extract_chunks_from_node(
                        tree.root_node, source_code, contract_id, toSlither)

                    if (toSlither):
                        contract = SlitherContract(
                            contract_id=contract_id,
                            chunks=chunks,
                        )
                    else:
                        # Add metadata to chunks
                        for chunk in chunks:
                            chunk.metadata.source_file = filename

                        contract = WorkingContract(
                            contract_id=contract_id,
                            repo_id=repo_id,
                            contract_name=primary_contract_name,
                            start_line=1,
                            end_line=len(source_code.split('\n')),
                            source_code=source_code,
                            chunks=chunks,
                            metadata={'source_file': filename,
                                      'repo_path': repo_path}
                        )

                        # add to contract collection
                        # insert_to_qdrant(contract, "working_contracts")

                    all_contracts.append(contract)

                else:
                    # Process each contract found
                    for contract_node in contract_nodes:
                        contract_name = self._extract_node_name(
                            contract_node) or "UnnamedContract"
                        print(f"    Found contract: {contract_name}")

                        contract_id = str(uuid.uuid4())
                        start_point = contract_node.start_point
                        end_point = contract_node.end_point

                        # Extract chunks from this specific contract
                        chunks = self._extract_chunks_from_node(
                            contract_node, source_code, contract_id, toSlither)

                        if (toSlither):
                            contract = SlitherContract(
                                contract_id=contract_id,
                                chunks=chunks,
                            )
                        else:
                            # Add metadata to chunks
                            for chunk in chunks:
                                chunk.metadata.source_file = filename

                            contract = WorkingContract(
                                contract_id=contract_id,
                                repo_id=repo_id,
                                contract_name=contract_name,
                                start_line=start_point[0] + 1,
                                end_line=end_point[0] + 1,
                                source_code=source_code,  # Full source for now
                                chunks=chunks,
                                metadata={'source_file': filename,
                                          'repo_path': repo_path}
                            )

                            # add to contract collection
                            # insert_to_qdrant(contract, "working_contracts")

                        all_contracts.append(contract)

                contracts_added = len(contract_nodes) if contract_nodes else 1
                total_chunks = sum(len(c.chunks)
                                   for c in all_contracts[-contracts_added:])
                print(
                    f"  Extracted {contracts_added} contracts with {total_chunks} total chunks")

            except (json.JSONDecodeError, KeyError) as e:
                raise ValueError(f"Invalid JSON in {filename}: {e}")
            except Exception as e:
                print(f"Error processing {filename}: {e}")
                continue

        # Create repository object
        if (toSlither):
            repo = SlitherRepo(
                contracts=all_contracts
            )
        else:
            repo = WorkingRepo(
                repo_id=repo_id,
                name=repo_name,
                url=repo_url,
                contracts=all_contracts,
                commit_hash=commit_hash,
                whitepaper=whitepaper,
                metadata={'repo_path': repo_path},
                created_at=datetime.now()
            )

            # add to respective collections
            # Insert repo (without nested contracts)
            repo_copy = repo.model_copy(deep=True)
            repo_copy.contracts = []
            insert_to_qdrant(repo_copy, os.getenv(
                "REPOS_COLLECTION_NAME", "demo_repos"))

            slither_chunks = []
            contract_id_to_name = {}  # Dictionary to map contract IDs to contract names

            # Put all contracts in the mythril shared volume (for mythril analysis with complicated imports)
            # update_mythril_shared_volume(repo.contracts)

            # Insert contracts (without nested chunks)
            for contract in repo.contracts:
                contract_copy = contract.model_copy(deep=True)
                contract_copy.chunks = []
                insert_to_qdrant(contract_copy, os.getenv(
                    "CONTRACTS_COLLECTION_NAME", "demo_contracts"))
                # print("calling insert on: ", contract_copy.contract_name)

                # Build contract_id_to_name dictionary
                contract_id_to_name[contract.contract_id] = contract.contract_name

                # Insert each chunk
                mythril_chunks = []  # condensed version of each chunk
                for chunk in contract.chunks:
                    insert_to_qdrant(chunk, os.getenv(
                        "CHUNKS_COLLECTION_NAME", "demo_chunks"), get_embedding)
                    slither_chunks.append(chunk.to_slither_chunk())
                    # to_slither_chunk() is used for both mythril and slither to condense chunk contents
                    mythril_chunks.append(chunk.to_slither_chunk())
                # analyze_chunks_with_mythril(mythril_chunks, contract.source_code, contract.contract_name, contract.contract_id)

            # Clear all contracts in the mythril shared volume (for mythril analysis with complicated imports)
            # clear_mythril_shared_volume()

            # print(f"DEBUG: Contract ID to name mapping: {contract_id_to_name}")
            # print(f"DEBUG: Sending {len(slither_chunks)} chunks to Slither service")
            # analyze_chunks_with_slither(slither_chunks, repo_url, contract_id_to_name)

        print(
            f"Repository '{repo_name}' created with {len(all_contracts)} contracts and {repo.get_chunk_count()} total chunks")
        return repo

    # Standalone function to chunk a single contract (not used by parse_project)
    def parse_code(self, source_code: str, contract_name: str, repo_id: str = str(uuid.uuid4())) -> WorkingContract:
        import faulthandler
        faulthandler.enable()
        """
        Simple test function: Parse Solidity source code and extract all chunks
        Treats entire source as one contract for testing purposes
        
        Args:
            source_code: The Solidity source code as a string
            contract_name: Name identifier for the contract
            repo_id: UUID of the parent repository
            
        Returns:
            WorkingContract object containing all chunks found in source
        """
        print("trying parse code")
        try:
            contract_id = str(uuid.uuid4())
            tree = self.parser.parse(bytes(source_code, 'utf8'))
            # try:
            #     print("starting parse", flush=True)
            #     tree = self.parser.parse(bytes(source_code, 'utf8'))
            #     print("tree made", flush=True)
            # except Exception as e:
            #     print("Error during parse:", e, flush=True)

            # Simply extract all chunks from the entire source
            chunks = self._extract_chunks_from_node(
                tree.root_node, source_code, contract_id)

            # Use provided contract name and cover entire source
            start_line = 1
            end_line = len(source_code.split('\n'))

            return WorkingContract(
                contract_id=contract_id,
                repo_id=repo_id,
                contract_name=contract_name,
                start_line=start_line,
                end_line=end_line,
                source_code=source_code,
                chunks=chunks,
                metadata={
                    'note': 'Simple test parsing - treats entire source as one contract'}
            )

        except Exception as e:
            print(f"Error parsing code: {e}")
            return WorkingContract(
                contract_id=str(uuid.uuid4()),
                repo_id=repo_id,
                contract_name=contract_name,
                start_line=1,
                end_line=1,
                source_code=source_code,
                chunks=[],
                metadata={'error': str(e)}
            )

    # Helper function for parse_code and parse_project
    def _extract_chunks_from_node(self, node: Node, source_code: str, contract_id: str, toSlither=False) -> Union[List[WorkingChunk], List[SlitherChunk]]:
        """Extract chunks from within a node (recursively)"""
        chunks = []

        # Check if this node itself should be chunked
        if node.type in self.chunkable_node_types:
            chunk = self._create_chunk(
                node, source_code, contract_id, toSlither)
            if chunk:
                chunks.append(chunk)
                # print("calling insert on: ", chunk.chunk_id)
                # insert_to_qdrant(chunk, "working_chunks", get_embedding)

        # Recursively check child nodes
        for child in node.children:
            # print("chunking child")
            child_chunks = self._extract_chunks_from_node(
                child, source_code, contract_id, toSlither)
            chunks.extend(child_chunks)

        return chunks

    # Helper function for parse_code and parse_project
    def _create_chunk(self, node: Node, source_code: str, contract_id: str, toSlither=False) -> Optional[Union[WorkingChunk, SlitherChunk]]:
        """Create a chunk object from an AST node"""
        # print("trying to create chunk")
        try:
            # Extract basic location info
            start_point = node.start_point
            end_point = node.end_point
            content = source_code[node.start_byte:node.end_byte]

            # Extract the name of this construct
            name = self._extract_node_name(node)
            if not name:
                name = f"unnamed_{node.type}"

            # Generate unique chunk ID
            chunk_id = str(uuid.uuid4())

            # Extract Solidity-specific metadata
            visibility = self._extract_visibility(node)
            mutability = self._extract_mutability(node)
            modifiers = self._extract_modifiers(node)
            parameters = self._extract_parameters(node, source_code)
            return_type = self._extract_return_type(node, source_code)

            if (toSlither):
                # Create condensed chunk
                chunk = SlitherChunk(
                    chunk_id=chunk_id,
                    contract_id=contract_id,
                    name=name,
                    start_line=start_point[0] + 1,  # Convert to 1-based
                    end_line=end_point[0] + 1,
                )
            else:
                # Create metadata object
                metadata = WorkingChunkMetadata(
                    descriptive_id=f"{node.type}_{name}_line_{start_point[0] + 1}",
                    visibility=visibility,
                    mutability=mutability,
                    modifier_list=modifiers,
                    parameters=parameters,
                    return_type=return_type,
                )

                # Create chunk
                chunk = WorkingChunk(
                    chunk_id=chunk_id,
                    contract_id=contract_id,
                    chunk_type=node.type,
                    name=name,
                    start_line=start_point[0] + 1,  # Convert to 1-based
                    end_line=end_point[0] + 1,
                    source_code=content,
                    metadata=metadata
                )

                # # add to chunks collections
                # insert_to_qdrant(chunk, "working_chunks", get_embedding)

            return chunk

        except Exception as e:
            print(f"Error creating chunk for {node.type}: {e}")
            return None

    '''
        HELPER FUNCTIONS TO EXTRACT RELEVANT SOLIDITY METADATA
    '''

    def _extract_node_name(self, node: Node) -> Optional[str]:
        """Extract the name/identifier from various node types"""

        # Most constructs have an 'identifier' child
        identifier_node = self._find_child_by_type(node, 'identifier')
        if identifier_node:
            return identifier_node.text.decode('utf-8')

        # Special cases
        if node.type == 'constructor':
            return 'constructor'
        elif node.type == 'fallback':
            return 'fallback'
        elif node.type == 'receive':
            return 'receive'

        return None

    def _extract_visibility(self, node: Node) -> Optional[str]:
        """Extract visibility modifier (public, private, internal, external)"""
        for child in node.children:
            if child.type == 'visibility' or child.text.decode('utf-8') in self.visibility_keywords:
                text = child.text.decode('utf-8')
                if text in self.visibility_keywords:
                    return text
        return None

    def _extract_mutability(self, node: Node) -> Optional[str]:
        """Extract mutability modifier (pure, view, payable, nonpayable)"""
        for child in node.children:
            text = child.text.decode('utf-8')
            if text in self.mutability_keywords:
                return text
        return None

    def _extract_modifiers(self, node: Node) -> List[str]:
        """Extract modifier names applied to functions"""
        modifiers = []

        # Look for modifier_invocation nodes
        for child in node.children:
            if child.type == 'modifier_invocation':
                # Find the identifier within the modifier invocation
                identifier = self._find_child_by_type(child, 'identifier')
                if identifier:
                    modifiers.append(identifier.text.decode('utf-8'))

        return modifiers

    def _extract_parameters(self, node: Node, source_code: str) -> List[Dict[str, str]]:
        """Extract parameter information from functions"""
        parameters = []

        # Find parameter_list node
        param_list = self._find_child_by_type(node, 'parameter_list')
        if not param_list:
            return parameters

        # Extract each parameter
        for child in param_list.children:
            if child.type == 'parameter':
                param_info = self._parse_parameter(child, source_code)
                if param_info:
                    parameters.append(param_info)

        return parameters

    def _parse_parameter(self, param_node: Node, source_code: str) -> Optional[Dict[str, str]]:
        """Parse a single parameter node"""
        try:
            param_text = param_node.text.decode('utf-8')

            # Simple parsing - could be enhanced
            parts = param_text.strip().split()
            if len(parts) >= 2:
                return {
                    'type': parts[0],
                    'name': parts[1] if len(parts) > 1 else '',
                    'full_text': param_text
                }
            elif len(parts) == 1:
                return {
                    'type': parts[0],
                    'name': '',
                    'full_text': param_text
                }
        except Exception as e:
            print(f"Error parsing parameter: {e}")

        return None

    def _extract_return_type(self, node: Node, source_code: str) -> Optional[str]:
        """Extract return type from function definitions"""
        # Look for returns clause
        for child in node.children:
            if child.type == 'returns':
                # Find the type within returns
                return_text = child.text.decode('utf-8')
                # Simple extraction - remove 'returns' and parentheses
                return_text = return_text.replace('returns', '').strip('() ')
                return return_text if return_text else None

        return None

    def _find_child_by_type(self, node: Node, target_type: str) -> Optional[Node]:
        """Helper to find child node by type"""
        for child in node.children:
            if child.type == target_type:
                return child
        return None

    # Utility function for easy testing
    def export_chunks_to_json(self, chunks: List[WorkingChunk], output_file: str):
        """Export chunks to JSON file for analysis"""
        chunk_dicts = [chunk.to_dict() for chunk in chunks]

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(chunk_dicts, f, indent=2, ensure_ascii=False)

        print(f"Exported {len(chunks)} chunks to {output_file}")

    # Helper function to find the node types in a contract for testing purposes
    # Used to decide which elements are chunked (included in self.chunkable_node_types)
    def discover_all_node_types(self, source_code: str):
        """Discover all node types in a Solidity file"""
        tree = self.parser.parse(bytes(source_code, 'utf8'))
        node_types = set()

        def collect_types(node):
            node_types.add(node.type)
            for child in node.children:
                collect_types(child)

        collect_types(tree.root_node)

        print("All node types found:")
        for node_type in sorted(node_types):
            print(f"  '{node_type}'")

        return node_types


''' 
    EXAMPLE USAGE AND TESTING
'''
# example of how deploy_pipeline should call parse_project()


def test_repo_chunking(repo_path: str = None, repo_url: str = None):
    # Initialize the chunker
    chunker = SolidityChunker()

    # Use provided arguments or fall back to default PURPOSE directory
    if repo_path is None:
        repo_path = "/Users/aditijain/shepherd-security/blackRabbit/deployments/PURPOSE"
    if repo_url is None:
        repo_url = "https://github.com/Purpose-for-Profit/PURPOSE"

    if os.path.exists(repo_path):
        try:
            print(f"Parsing contracts from repository: {repo_path}")
            demo_repo = chunker.parse_project(
                repo_path=repo_path, repo_url=repo_url)

            print(f"Repository: {demo_repo.name}")
            print(f"Total contracts: {len(demo_repo.contracts)}")
            print(f"Total chunks: {demo_repo.get_chunk_count()}")

            # Collect all chunks from all contracts
            all_chunks_data = []

            for contract in demo_repo.contracts:
                print(
                    f"\nContract: {contract.contract_name} ({len(contract.chunks)} chunks)")

                for chunk in contract.chunks:
                    # Convert chunk to dict and add contract context
                    chunk_data = chunk.to_dict()
                    chunk_data['parent_contract_name'] = contract.contract_name
                    chunk_data['repo_name'] = demo_repo.name
                    all_chunks_data.append(chunk_data)

                    # Print summary of each chunk
                    print(
                        f"  - {chunk.chunk_type}: {chunk.name} (lines {chunk.start_line}-{chunk.end_line})")

            # Export all chunks to JSON file
            export_filename = f"all_chunks_export_{demo_repo.name.replace('/', '_')}.json"
            with open(export_filename, 'w', encoding='utf-8') as f:
                json.dump(all_chunks_data, f, indent=2,
                          ensure_ascii=False, default=str)

            print(
                f"\n✅ Exported {len(all_chunks_data)} chunks to '{export_filename}'")

            return demo_repo

        except (FileNotFoundError, ValueError) as e:
            print(f"Repository parsing error: {e}")
            return None
    else:
        print(
            f"Repository path '{repo_path}' not found - skipping repository test")
        print("\nTo test repository parsing, create a directory with JSON files like:")
        print('{"contract_name": "MyToken", "source_code": "pragma solidity ^0.8.0;\\ncontract MyToken { ... }"}')
        return None

# Example of how to chunk a single contract


def test_contract_chunking():
    chunker = SolidityChunker()

    # Sample Solidity contract with various elements
    test_contract = '''
    pragma solidity ^0.8.0;
    
    contract TestToken {
        // Constants
        uint256 constant USDC_DECIMALS = 6;
        uint256 constant STANDARD_DECIMALS = 18;
        
        // State variables
        string public name = "Test Token";
        mapping(address => uint256) public balances;
        address public owner;
        uint256 private _totalSupply;
        
        // Events
        event Transfer(address indexed from, address indexed to, uint256 value);
        event Approval(address indexed owner, address indexed spender, uint256 value);
        
        // Custom errors
        error InsufficientBalance(uint256 requested, uint256 available);
        error Unauthorized();
        
        // Structs
        struct TokenInfo {
            string symbol;
            uint256 decimals;
            bool isActive;
        }
        
        // Enums
        enum Status { Pending, Active, Suspended }
        
        // Modifiers
        modifier onlyOwner() {
            require(msg.sender == owner, "Not the owner");
            _;
        }
        
        modifier validAddress(address addr) {
            require(addr != address(0), "Invalid address");
            _;
        }
        
        // Constructor
        constructor() {
            owner = msg.sender;
            _totalSupply = 1000000 * 10**18;
            balances[msg.sender] = _totalSupply;
        }
        
        // Functions
        function transfer(address to, uint256 amount) public validAddress(to) returns (bool) {
            uint256 senderBalance = balances[msg.sender];
            if (senderBalance < amount) {
                revert InsufficientBalance(amount, senderBalance);
            }
            
            balances[msg.sender] -= amount;
            balances[to] += amount;
            
            emit Transfer(msg.sender, to, amount);
            return true;
        }
        
        function approve(address spender, uint256 amount) public returns (bool) {
            emit Approval(msg.sender, spender, amount);
            return true;
        }
        
        function getBalance(address account) public view returns (uint256) {
            return balances[account];
        }
        
        function mint(address to, uint256 amount) public onlyOwner {
            _totalSupply += amount;
            balances[to] += amount;
            emit Transfer(address(0), to, amount);
        }
        
        // Receive function
        receive() external payable {
            // Handle plain ether transfers
        }
        
        // Fallback function
        fallback() external {
            revert("Function not found");
        }
    }
    '''

    print("=== Testing parse_code ===")

    # Parse the contract
    contract = chunker.parse_code(test_contract, "TestToken")

    # View the chunks in test_export.json
    chunker.export_chunks_to_json(contract.chunks, "test_contract_export")


def test_slither_chunking():
    # Initialize the chunker
    chunker = SolidityChunker()

    # Example chunking on the PURPOSE directory
    repo_path = "/Users/aditijain/shepherd-security/blackRabbit/deployments/PURPOSE"

    print(f"Parsing contracts from repository: {repo_path}")
    slither_repo = chunker.parse_project(repo_path=repo_path, toSlither=True)
    print(slither_repo)

    print(f"Total contracts: {len(slither_repo.contracts)}")

    # Collect all chunks from all contracts
    all_chunks_data = []

    for contract in slither_repo.contracts:
        for chunk in contract.chunks:
            # Convert chunk to dict and add contract context
            chunk_data = chunk.to_dict()
            all_chunks_data.append(chunk_data)

    # Export all chunks to JSON file
    with open("all_slither_chunks_export.json", 'w', encoding='utf-8') as f:
        json.dump(all_chunks_data, f, indent=2,
                  ensure_ascii=False, default=str)

    print(
        f"\n✅ Exported {len(all_chunks_data)} chunks to 'all_slither_chunks_export.json'")


# Run the test
if __name__ == "__main__":
    # slither_repo = test_slither_chunking()
    demo_repo = test_repo_chunking()
    # contract = test_contract_chunking()
