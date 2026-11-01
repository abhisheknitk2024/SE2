from pydantic import BaseModel, Field, field_validator

class RequestModel(BaseModel):
    """
    Request model for the API.
    """
    message: str = Field(min_length=10,max_length=1000, description="The message to be sent to the consumer.")
    producer: str
    """
    Validates the producer field.
    """

    @field_validator('producer')
    @classmethod
    def validate_producer(RequestModel, value):
        if not value:
            raise ValueError("Producer name cannot be empty.")
        return value
