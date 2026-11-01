from fastapi import FastAPI
from models.response import ResponseModel
from models.request import RequestModel

app = FastAPI()

@app.get("/")
async def read_root():
    return ResponseModel(status="success", message="Hello, World!")


@app.post("/submit")
async def submit_data(RequestModel: RequestModel):
    return ResponseModel(status="success", message=f"Received message: {RequestModel.message} from producer: {RequestModel.producer}")
