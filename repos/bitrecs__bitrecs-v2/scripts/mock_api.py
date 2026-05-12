
from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel
import uvicorn

app = FastAPI()

# 1. Simulate getting agent (return 404 so CLI asks for a name)
@app.get("/retrieval/agent-by-hotkey")
def get_agent(miner_hotkey: str):
    return {} # Return empty or 404, CLI handles "else" branch by asking for name

# 2. Simulate Check
@app.post("/upload/agent/check")
def check_agent(
    public_key: str = Form(...),
    file_info: str = Form(...),
    signature: str = Form(...),
    name: str = Form(...),
    payment_time: float = Form(...)
):
    return {"status": "ok"}

# 3. Simulate Pricing - RETURNING 0.01 Alpha to test failure
@app.get("/upload/eval-pricing")
def get_pricing():
    return {
        "amount_rao": 100000000000, # 100.00 ALPHA 
        "send_address": "5HeBjnn2YRoBhjt6sh9yT7RzyAH4ACq9os8W5zsHTwBEFmZ3" 
    }

# 4. Simulate Final Upload
@app.post("/upload/agent")
def upload_agent(
    public_key: str = Form(...),
    file_info: str = Form(...),
    signature: str = Form(...),
    name: str = Form(...),
    payment_block_hash: str = Form(...),
    payment_extrinsic_index: int = Form(...),
    payment_time: float = Form(...)
):
    print(f"SUCCESS! Received payment proof.")
    print(f"Block Hash: {payment_block_hash}")
    print(f"Extrinsic Index: {payment_extrinsic_index}")
    return {"status": "success"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
