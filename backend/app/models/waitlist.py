from pydantic import BaseModel

class WaitlistRequest(BaseModel):
    email: str
