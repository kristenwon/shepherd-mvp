from pydantic import BaseModel


class UpdateSessionNameRequest(BaseModel):
    session_name: str
