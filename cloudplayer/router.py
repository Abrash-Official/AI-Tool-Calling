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
    output_dir = "temp_audio"
    os.makedirs(output_dir, exist_ok=True)

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
                raise HTTPException(status_code=400, detail=f"API Error: {data.get('msg', 'Unknown error')}")

        if not download_link:
            raise HTTPException(status_code=400, detail="No download link received.")

        file_path = os.path.join(output_dir, f"{video_title}.mp3")
        mp3_res = requests.get(download_link, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        with open(file_path, "wb") as f:
            for chunk in mp3_res.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)

        folder_id = get_or_create_folder("MyCloudPlayer", req.access_token)
        
        # --- THE FINAL FIX: METADATA FIRST, MEDIA SECOND ---
        
        # 1. Create the file metadata FIRST to force audio/mpeg MIME type
        metadata_url = "https://www.googleapis.com/drive/v3/files"
        metadata_headers = {
            "Authorization": f"Bearer {req.access_token}",
            "Content-Type": "application/json"
        }
        metadata = {
            'name': f"{video_title}.mp3",
            'parents': [folder_id],
            'mimeType': 'audio/mpeg'
        }
        
        meta_res = requests.post(metadata_url, headers=metadata_headers, json=metadata)
        if meta_res.status_code not in (200, 201):
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=meta_res.status_code, detail=meta_res.text)
            
        file_id = meta_res.json().get("id")

        # 2. Upload the raw audio bytes to that specific file ID using PATCH
        upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
        upload_headers = {
            "Authorization": f"Bearer {req.access_token}",
            "Content-Type": "audio/mpeg"
        }
        
        with open(file_path, "rb") as media_file:
            upload_res = requests.patch(upload_url, headers=upload_headers, data=media_file)

        if os.path.exists(file_path):
            os.remove(file_path)

        if upload_res.status_code in (200, 201):
            return {"status": "success", "file": upload_res.json()}
        else:
            raise HTTPException(status_code=upload_res.status_code, detail=upload_res.text)

    except Exception as e:
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=str(e))