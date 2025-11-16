from dotenv import load_dotenv
import firebase_admin
from pathlib import Path
import hashlib
import zipfile
import io
import os
import json
import tempfile
import pathlib
import uuid
from firebase_admin import credentials, firestore, storage
from datetime import datetime
from typing import Optional, Dict, Any, List
from .models.scoped_contracts import ContractsList, Contract
from .user_deployment import build_contract_assets_to_mas

load_dotenv()


def initialize_firebase():
    """Initialize Firebase Admin SDK if not already initialized"""
    try:
        firebase_admin.get_app()
    except ValueError:
        # Firebase not initialized yet
        service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        if service_account_path:
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
        else:
            raise ValueError(
                "FIREBASE_SERVICE_ACCOUNT_PATH not found in environment variables")


def get_firestore_client():
    """Get Firestore client instance"""
    initialize_firebase()
    return firestore.client()


def save_email_to_firestore(email: str) -> None:
    """When user gets at capacity pop up, save email to Firestore collection 'waitlist'"""
    db = get_firestore_client()
    document_id = str(uuid.uuid4())
    doc_ref = db.collection("waitlist").document(document_id)
    doc_ref.set({
        "email": email,
        "timestamp": firestore.SERVER_TIMESTAMP
    })


def save_hypothesis_to_firestore(run_id: str, hypothesis: str, github_url: str, user_id: str = None) -> None:
    """Save hypothesis to Firestore collection 'hypotheses'"""
    db = get_firestore_client()
    doc_ref = db.collection(
        os.getenv("HYPOTHESIS_COLLECTION")).document(run_id)
    doc_ref.set({
        "run_id": run_id,
        "hypothesis": hypothesis,
        "github_url": github_url,
        "timestamp": firestore.SERVER_TIMESTAMP
    })


def save_run_request_to_firestore(
    run_id: str,
    github_url: str,
    tunnel_url: str,
    assets_path: Optional[str] = None,
    assets_metadata: Optional[Dict[str, Any]] = None,
    status: str = "started"
) -> Dict[str, Any]:
    """
    Save run request data to Firestore collection 'runs'

    Args:
        run_id: Unique identifier for the run
        github_url: GitHub repository URL
        tunnel_url: Tunnel URL for the run
        assets_path: Local path where assets file was saved
        assets_metadata: Metadata about the uploaded assets file
        status: Initial status of the run

    Returns:
        Dict containing the saved document data
    """
    db = get_firestore_client()

    # Prepare the document data
    doc_data = {
        "run_id": run_id,
        "github_url": github_url,
        "tunnel_url": tunnel_url,
        "status": status,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    # Add assets information if provided
    if assets_path:
        doc_data["assets_path"] = assets_path

    if assets_metadata:
        doc_data["assets_metadata"] = assets_metadata

    # Save to Firestore
    doc_ref = db.collection("runs").document(run_id)
    doc_ref.set(doc_data)

    # Return the data (with client-side timestamp for immediate use)
    doc_data["created_at"] = datetime.utcnow().isoformat()
    doc_data["updated_at"] = datetime.utcnow().isoformat()

    return doc_data


def update_run_status_in_firestore(
    run_id: str,
    status: str,
    additional_data: Optional[Dict[str, Any]] = None,
    create_if_missing: bool = True  # ← NEW PARAMETER
) -> None:
    """Update the status of a run in Firestore."""
    try:
        db = get_firestore_client()
        doc_ref = db.collection("runs").document(run_id)

        update_data = {
            "run_id": run_id,
            "status": status,
            "updated_at": firestore.SERVER_TIMESTAMP
        }

        if status in ["completed", "failed", "cancelled", "at_capacity"]:
            update_data[f"{status}_at"] = firestore.SERVER_TIMESTAMP

        if additional_data:
            update_data.update(additional_data)

        # ✅ Use set with merge instead of update
        if create_if_missing:
            doc_ref.set(update_data, merge=True)
        else:
            doc_ref.update(update_data)

        print(f"✅ Updated Firestore status: {run_id} -> {status}")

    except Exception as e:
        print(f"⚠️ Error updating Firestore: {e}")
        # Don't raise


def get_run_from_firestore(run_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a run document from Firestore

    Args:
        run_id: Unique identifier for the run

    Returns:
        Dict containing the run data or None if not found
    """
    db = get_firestore_client()
    doc_ref = db.collection("runs").document(run_id)
    doc = doc_ref.get()

    if doc.exists:
        return doc.to_dict()
    return None


def repo_display_name(src: str) -> str:
    """Nicely-formatted folder name for deployment artefacts."""
    if src.startswith("http"):
        # For GitHub URLs, extract the repo name from the URL path
        if "github.com" in src:
            # Handle URLs like https://github.com/owner/repo or https://github.com/owner/repo.git
            parts = src.rstrip('/').split('/')
            if len(parts) >= 2:
                repo_name = parts[-1]
                # Remove .git extension if present
                if repo_name.endswith('.git'):
                    repo_name = repo_name[:-4]
                return repo_name
        # Fallback to original logic for other HTTP URLs
        stem = pathlib.Path(src).stem  # e.g. repo.git
        return stem[:-4] if stem.endswith(".git") else stem
    return pathlib.Path(src).name


def get_all_contracts(run_id: str, assets_data: bytes) -> ContractsList:
    contract_list: List[ContractsList] = []
    try:
        # Use a temporary directory that auto-deletes when the block ends
        # with tempfile.TemporaryDirectory(prefix=f"mas_extract_{run_id}_") as temp_dir:
        temp_dir = tempfile.mkdtemp(prefix=f"mas_extract_{run_id}_")
        print(f"Temporary directory created at: {temp_dir}")

        extract_dir = Path(temp_dir) / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        # Extract ZIP with improved logic
        if not extract_zip_safely(assets_data, extract_dir):
            error_msg = "Failed to extract ZIP file properly"
            print(f"ERROR: {error_msg}")

    except Exception as e:
        print(f"❌ Error during extraction/processing: {e}")
        import traceback
        traceback.print_exc()
        # Don't delete temp dir on error for debugging
        print(f"🔍 DEBUG: Temporary directory preserved at: {temp_dir}")
        raise

    # Note: NOT cleaning up temp_dir for debugging purposes
    print(f"✅ Extraction complete.")
    src_dir = extract_dir / "src"
    if not src_dir.exists() or not src_dir.is_dir():
        print(f"⚠️ Warning: src/ directory not found in extracted files")
    for sol_path in src_dir.rglob("*.sol"):
        contract_list.append(
            Contract(
                contract_name=sol_path.name,
                is_deployed=False,
                is_in_scope=False
            )
        )

    # Step 1 — locate run-latest.json anywhere in extract_dir
    run_latest_path = None
    for p in extract_dir.rglob("run-latest.json"):
        run_latest_path = p
        break

    if run_latest_path is None:
        print("⚠️ No run-latest.json found in extracted files")
        deployed_names = set()
    else:
        print(f"📄 Found run-latest.json at: {run_latest_path}")

        # Step 2 — read the JSON file
        try:
            with open(run_latest_path, "r") as f:
                run_data = json.load(f)

            # Step 3 — extract contract names from run_data["transactions"]
            deployed_names = {
                tx.get("contractName")
                for tx in run_data.get("transactions", [])
                if tx.get("transactionType") == "CREATE"
            }

            print(
                f"🚀 Deployed contractNames found in broadcast: {deployed_names}")

        except Exception as e:
            print(f"❌ Error reading run-latest.json: {e}")
            deployed_names = set()

    # Step 4 — mark contract_list entries as deployed
    for c in contract_list:
        if c.contract_name.replace(".sol", "") in deployed_names:
            c.is_deployed = True
            c.is_in_scope = True

    # print(f'contract_list: {contract_list}')

    return ContractsList(contracts=contract_list)


def extract_zip_safely(assets_data: bytes, extract_dir: Path) -> bool:
    """
    Safely extract ZIP file with better root folder detection and error handling
    """
    try:
        # Log ZIP checksum for debugging
        zip_hash = hashlib.md5(assets_data).hexdigest()
        print(f"📊 ZIP MD5: {zip_hash}")
        print(f"📦 ZIP Size: {len(assets_data)} bytes")

        with zipfile.ZipFile(io.BytesIO(assets_data), 'r') as zf:
            members = zf.namelist()

            # Filter out __MACOSX files FIRST
            filtered_members = [
                m for m in members
                if not m.startswith('__MACOSX/') and '/__MACOSX/' not in m
                # Also filter ._ files
                and not m.startswith('._') and '/._' not in m
            ]

            print(
                f"📦 ZIP contains {len(members)} total items ({len(filtered_members)} after filtering __MACOSX)")

            if not filtered_members:
                print("⚠️ Warning: ZIP file is empty after filtering")
                return False

            # Log filtered ZIP contents for debugging
            print(f"📦 Filtered ZIP contents (first 10 items):")
            for member in filtered_members[:10]:
                try:
                    info = zf.getinfo(member)
                    print(
                        f"  {info.filename} - {info.file_size} bytes - {'DIR' if info.is_dir() else 'FILE'}")
                except:
                    print(f"  {member}")
            if len(filtered_members) > 10:
                print(f"  ... and {len(filtered_members) - 10} more items")

            # Better root folder detection using FILTERED members
            root_folder = detect_root_folder(filtered_members)

            if root_folder:
                print(f"📁 Detected root folder in ZIP: {root_folder}")
            else:
                print("📁 No common root folder detected")

            extracted_count = 0
            skipped_count = 0
            failed_count = 0
            macosx_skipped = len(members) - len(filtered_members)

            for member in members:
                # Skip __MACOSX files and ._ files
                if (member.startswith('__MACOSX/') or '/__MACOSX/' in member or
                        member.startswith('._') or '/._' in member):
                    continue

                # Skip .DS_Store files
                if '.DS_Store' in member:
                    skipped_count += 1
                    continue

                # Skip the root folder itself
                if root_folder and (member == root_folder or member == root_folder.rstrip('/')):
                    skipped_count += 1
                    continue

                # Calculate the target path
                if root_folder and member.startswith(root_folder):
                    # Strip the root folder from the path
                    relative_path = member[len(root_folder):]
                    if not relative_path:  # Empty after stripping
                        skipped_count += 1
                        continue
                else:
                    relative_path = member

                # Security check: prevent directory traversal
                if '..' in relative_path or relative_path.startswith('/'):
                    print(f"⚠️ Skipping potentially unsafe path: {member}")
                    skipped_count += 1
                    continue

                target_path = extract_dir / relative_path

                # Handle directories
                if member.endswith('/'):
                    target_path.mkdir(parents=True, exist_ok=True)
                    extracted_count += 1
                else:
                    # Ensure parent directory exists
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    # Extract file
                    try:
                        with zf.open(member) as source:
                            content = source.read()
                            with open(target_path, 'wb') as target:
                                target.write(content)
                        extracted_count += 1
                    except Exception as e:
                        print(f"⚠️ Failed to extract {member}: {e}")
                        failed_count += 1
                        continue

            print(f"✅ Extraction summary:")
            print(f"   - Successfully extracted: {extracted_count} items")
            print(f"   - Skipped __MACOSX: {macosx_skipped} items")
            print(f"   - Skipped other: {skipped_count} items")
            print(f"   - Failed: {failed_count} items")
            print(
                f"   - Total processed: {extracted_count + skipped_count + failed_count}/{len(filtered_members)} (excluding __MACOSX)")

            # Verify expected structure
            verify_extracted_structure(extract_dir)

            return True

    except zipfile.BadZipFile as e:
        print(f"❌ Error: Invalid ZIP file - {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error during extraction: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_extracted_structure(extract_dir: Path):
    """
    Verify the extracted structure contains expected Foundry directories
    """
    expected_dirs = ['out', 'broadcast', 'src']
    found_dirs = []
    missing_dirs = []

    for dir_name in expected_dirs:
        dir_path = extract_dir / dir_name
        if dir_path.exists() and dir_path.is_dir():
            found_dirs.append(dir_name)
            print(f"✅ Found Foundry {dir_name}/ directory")
        else:
            missing_dirs.append(dir_name)

    if missing_dirs:
        print(f"⚠️ Warning: Missing expected directories: {missing_dirs}")

        # Debug: Show what was actually extracted
        print("\n📂 Extracted structure:")
        for item in extract_dir.iterdir():
            if item.is_dir():
                print(f"  📁 {item.name}/")
                # Show first level of subdirectories
                try:
                    # Limit to 5 items
                    for subitem in list(item.iterdir())[:5]:
                        if subitem.is_dir():
                            print(f"    📁 {subitem.name}/")
                        else:
                            print(f"    📄 {subitem.name}")
                except:
                    pass
            else:
                print(f"  📄 {item.name}")


def detect_root_folder(members: List[str]) -> Optional[str]:
    """
    More robust detection of common root folder in ZIP
    """
    if not members:
        return None

    # Method 1: Check if all files share a common prefix directory
    # Get all top-level items
    top_level_items = set()
    for member in members:
        parts = member.split('/')
        if parts[0]:  # Ignore empty parts
            top_level_items.add(parts[0])

    # If there's exactly one top-level item and it appears in all paths
    if len(top_level_items) == 1:
        potential_root = list(top_level_items)[0] + '/'

        # Verify all members start with this root (except the root itself)
        all_under_root = all(
            m == potential_root.rstrip('/') or m.startswith(potential_root)
            for m in members
        )

        if all_under_root:
            return potential_root

    # Method 2: Check for common path patterns (e.g., "projectname-main/")
    # Common patterns from GitHub/GitLab archives
    for member in members:
        if '/' in member:
            potential_root = member.split('/')[0] + '/'
            # Check if this looks like an auto-generated archive root
            # (contains version, branch name, or common suffixes)
            if any(suffix in potential_root.lower()
                   for suffix in ['-main', '-master', '-dev', '-v', '-release']):
                # Verify this is actually a root
                if all(m == potential_root.rstrip('/') or m.startswith(potential_root)
                       for m in members):
                    return potential_root

    return None
