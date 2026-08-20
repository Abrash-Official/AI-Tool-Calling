import os
import re
import json
import time
import requests
import urllib.parse as urlparse
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# This will automatically find the .env in the root directory
load_dotenv()

# Use APIRouter instead of FastAPI() to keep this separate
router = APIRouter()

class DownloadRequest(BaseModel):
    video_url: str
    access_token: str

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name)

def get_or_create_folder(folder_name: str, access_token: str) -> str:
    headers = {"Authorization": f"Bearer {access_token}"}
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    
    search_url = f"https://www.googleapis.com/drive/v3/files?q={urlparse.quote(query)}"
    
    res = requests.get(search_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail="Failed to query user Google Drive.")
    
    files = res.json().get('files', [])
    if files:
        return files[0]['id']
    
    create_url = "https://www.googleapis.com/drive/v3/files"
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    create_res = requests.post(create_url, headers=headers, json=folder_metadata)
    if create_res.status_code not in (200, 201):
        raise HTTPException(status_code=create_res.status_code, detail="Failed to create folder in Google Drive.")
    
    return create_res.json().get('id')

@router.post("/api/download-and-save")
def download_and_save(req: DownloadRequest):
    parsed = urlparse.urlparse(req.video_url)
    video_id = urlparse.parse_qs(parsed.query).get('v')
    if not video_id:
        video_id = parsed.path.split('/')[-1]
    else:
        video_id = video_id[0]

    api_url = "https://youtube-mp36.p.rapidapi.com/dl" 
    querystring = {"id": video_id}
    headers = {
        "X-RapidAPI-Key": os.getenv("X-rapidapi-key"),
        "X-RapidAPI-Host": "youtube-mp36.p.rapidapi.com"
    }

    try:
        download_link = None
        video_title = video_id
        
        while True:
            response = requests.get(api_url, headers=headers, params=querystring)
            response.raise_for_status() 
            data = response.json()
            status = data.get("status")
            
            if status == "processing":
                time.sleep(2) 
            elif status == "ok":
                download_link = data.get("link")
                raw_title = data.get("title")
                if raw_title:
                    video_title = sanitize_filename(raw_title)
                break 
            else:
                raise HTTPException(status_code=400, detail=f"RapidAPI Error: {data.get('msg', 'Unknown error')}")

        if not download_link:
            raise HTTPException(status_code=400, detail="No download link received from API.")

        # 1. Download directly into memory (RAM)
        mp3_response = requests.get(download_link, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        mp3_response.raise_for_status()

        # 2. Strict Validation: Check if the API blocked Render and returned an HTML page instead of an MP3
        content_type = mp3_response.headers.get('Content-Type', '').lower()
        if 'text' in content_type or 'html' in content_type:
            raise HTTPException(status_code=403, detail="Download blocked. The provider returned a text/HTML error page instead of an audio file. Render's IP might be blocked.")
        
        audio_data = mp3_response.content
        
        # 3. Size Validation: If it's less than 100KB, it's definitely not a full song
        if len(audio_data) < 100000:
            raise HTTPException(status_code=400, detail="The downloaded file is way too small to be a song. The API likely returned a silent error.")

        folder_id = get_or_create_folder("MyCloudPlayer", req.access_token)
        
        # 4. Construct the multipart payload entirely in memory
        metadata = {
            'name': f"{video_title}.mp3",
            'parents': [folder_id],
            'mimeType': 'audio/mpeg'
        }
        
        boundary = "-------314159265358979323846"
        
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode('utf-8'))
        body.extend(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
        body.extend(json.dumps(metadata).encode('utf-8'))
        body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode('utf-8'))
        body.extend(b"Content-Type: audio/mpeg\r\n\r\n")
        body.extend(audio_data)  # Append the raw audio from RAM
        body.extend(f"\r\n--{boundary}--\r\n".encode('utf-8'))
        
        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
        upload_headers = {
            "Authorization": f"Bearer {req.access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
            "Content-Length": str(len(body))
        }
        
        # 5. Push the memory buffer directly to Drive
        upload_res = requests.post(upload_url, headers=upload_headers, data=body)

        if upload_res.status_code in (200, 201):
            return {"status": "success", "file": upload_res.json()}
        else:
            raise HTTPException(status_code=upload_res.status_code, detail=f"Drive Upload Error: {upload_res.text}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))