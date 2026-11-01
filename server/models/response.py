from pydantic import BaseModel

class ResponseModel(BaseModel):
    """
    Response model for the API.
    """
    status: str
    message: str