from fastapi import FastAPI
from models.request import RequestModel
from models.response import ResponseModel
from psycopg2 import connect, sql

from dotenv import load_dotenv
import os   

load_dotenv()


connection = connect(user=os.getenv("USERNAME"), password=os.getenv("PASSWORD"), host=os.getenv("HOST"), port=os.getenv("PORT"), database=os.getenv("DATABASE"))
cursor = connection.cursor()

app = FastAPI()

@app.get("/")
async def root():
    return ResponseModel(status="success", message="Hello, World!")


@app.post("/submitJob")
async def submit_job(request_model: RequestModel):
    try:
        insert_query = sql.SQL("INSERT INTO jobs (message, prodcer) VALUES (%s, %s)")
        cursor.execute(insert_query, (request_model.message, request_model.producer))
        connection.commit()     
        return ResponseModel(status="success"
                             , message=f"Received message: {request_model.message} from producer: {request_model.producer}")
    except Exception as e:
        connection.rollback()
        return ResponseModel(status="error", message=f"Failed to insert job: {str(e)}") 