#!/usr/bin/env python3
import os

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

load_dotenv()  # Load variables from .env file

def get_env_var(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Environment variable {name} is not set.")
    return value

host_addr = get_env_var("HOST_ADDR")
username = get_env_var("USERNAME")
password = get_env_var("PASSWORD")
dji_app_id = get_env_var("DJI_APP_ID")
dji_app_key = get_env_var("DJI_APP_KEY")
dji_license = get_env_var("DJI_LICENSE")

host_addr = os.environ["HOST_ADDR"]
username = os.environ["USERNAME"]
password = os.environ["PASSWORD"]
dji_app_id = os.environ["DJI_APP_ID"]
dji_app_key = os.environ["DJI_APP_KEY"]
dji_license = os.environ["DJI_LICENSE"]

app = FastAPI()


@app.get("/login")
async def pilot_login():
    file_path = "./cloudhtml/login.html"
    with open(file_path, 'r', encoding='utf-8') as file:
        file_content = file.read()
    file_content = file_content.replace("{{HOST_ADDR}}", host_addr)
    file_content = file_content.replace("{{USERNAME}}", username)
    file_content = file_content.replace("{{PASSWORD}", password)
    file_content = file_content.replace("{{DJI_APP_ID}}", dji_app_id)
    file_content = file_content.replace("{{DJI_LICENSE}}", dji_license)
    file_content = file_content.replace("{{DJI_APP_KEY}}", dji_app_key)
    return HTMLResponse(file_content)


if __name__ == "__main__":
    uvicorn.run(app, host=host_addr, port=3000)
