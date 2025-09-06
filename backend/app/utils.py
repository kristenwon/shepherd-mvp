from dotenv import load_dotenv
import firebase_admin, os, uuid
from firebase_admin import credentials, firestore, storage


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
            raise ValueError("FIREBASE_SERVICE_ACCOUNT_PATH not found in environment variables")
        
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

def save_hypothesis_to_firestore(run_id: str, hypothesis: str, user_id: str = None) -> None:
    """Save hypothesis to Firestore collection 'hypotheses'"""
    db = get_firestore_client()
    doc_ref = db.collection(os.getenv("HYPOTHESIS_COLLECTION")).document(run_id)
    doc_ref.set({
        "run_id": run_id,
        "hypothesis": hypothesis,
        "timestamp": firestore.SERVER_TIMESTAMP
    })