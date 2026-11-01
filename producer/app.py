from fastapi import FastAPI
from models.response import ResponseModel
from models.request import RequestModel
import requests
from dotenv import load_dotenv
import os
load_dotenv()

app = FastAPI()

@app.get("/")
async def read_root():
    return ResponseModel(status="success", message="Hello, World!")


@app.post("/submit")
async def submit_data(RequestModel: RequestModel):
    #connect to the microdervice at 8003 with endpoint /submitJob and send the data to it
    response = requests.post(f"{os.getenv('SERVER_URL')}/submitJob", json=RequestModel.model_dump())
    if response.status_code != 200:
        return ResponseModel(status="error", message=f"Failed to submit data to microservice: {response.text}")
    else:
        return ResponseModel(status="success", message=f"Data submitted to microservice: {response.text}")
