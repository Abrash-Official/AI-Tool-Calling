import os
import re
import json
import time
import requests
import urllib.parse as urlparse
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# This will automatically find the .env in the root directory[cite: 6]
load_dotenv()

# Use APIRouter instead of FastAPI() to keep this separate[cite: 6]
router = APIRouter()

class DownloadRequest(BaseModel):
    video_url: str
    access_token: str

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name)[cite: 6]

def get_or_create_folder(folder_name: str, access_token: str) -> str:
    headers = {"Authorization": f"Bearer {access_token}"}[cite: 6]
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"[cite: 6]
    
    # FIXED: using urlparse instead of urllib.parse[cite: 6]
    search_url = f"https://www.googleapis.com/drive/v3/files?q={urlparse.quote(query)}"[cite: 6]
    
    res = requests.get(search_url, headers=headers)[cite: 6]
    if res.status_code != 200:[cite: 6]
        raise HTTPException(status_code=res.status_code, detail="Failed to query user Google Drive.")[cite: 6]
    
    files = res.json().get('files', [])[cite: 6]
    if files:[cite: 6]
        return files[0]['id'][cite: 6]
    
    create_url = "https://www.googleapis.com/drive/v3/files"[cite: 6]
    folder_metadata = {
        'name': folder_name,[cite: 6]
        'mimeType': 'application/vnd.google-apps.folder'[cite: 6]
    }
    create_res = requests.post(create_url, headers=headers, json=folder_metadata)[cite: 6]
    if create_res.status_code not in (200, 201):[cite: 6]
        raise HTTPException(status_code=create_res.status_code, detail="Failed to create folder in Google Drive.")[cite: 6]
    
    return create_res.json().get('id')[cite: 6]

@router.post("/api/download-and-save")
def download_and_save(req: DownloadRequest):
    output_dir = "temp_audio"[cite: 6]
    os.makedirs(output_dir, exist_ok=True)[cite: 6]

    parsed = urlparse.urlparse(req.video_url)[cite: 6]
    video_id = urlparse.parse_qs(parsed.query).get('v')[cite: 6]
    if not video_id:[cite: 6]
        video_id = parsed.path.split('/')[-1][cite: 6]
    else:
        video_id = video_id[0][cite: 6]

    api_url = "https://youtube-mp36.p.rapidapi.com/dl"[cite: 6]
    querystring = {"id": video_id}[cite: 6]
    headers = {
        "X-RapidAPI-Key": os.getenv("X-rapidapi-key"),[cite: 6]
        "X-RapidAPI-Host": "youtube-mp36.p.rapidapi.com"[cite: 6]
    }

    try:
        download_link = None[cite: 6]
        video_title = video_id[cite: 6]
        
        while True:
            response = requests.get(api_url, headers=headers, params=querystring)[cite: 6]
            response.raise_for_status()[cite: 6]
            data = response.json()[cite: 6]
            status = data.get("status")[cite: 6]
            
            if status == "processing":[cite: 6]
                time.sleep(2)[cite: 6]
            elif status == "ok":[cite: 6]
                download_link = data.get("link")[cite: 6]
                raw_title = data.get("title")[cite: 6]
                if raw_title:[cite: 6]
                    video_title = sanitize_filename(raw_title)[cite: 6]
                break[cite: 6]
            else:
                raise HTTPException(status_code=400, detail=f"API Error: {data.get('msg', 'Unknown error')}")[cite: 6]

        if not download_link:[cite: 6]
            raise HTTPException(status_code=400, detail="No download link received.")[cite: 6]

        file_path = os.path.join(output_dir, f"{video_title}.mp3")[cite: 6]
        mp3_res = requests.get(download_link, stream=True, headers={"User-Agent": "Mozilla/5.0"})[cite: 6]
        with open(file_path, "wb") as f:[cite: 6]
            for chunk in mp3_res.iter_content(chunk_size=1024):[cite: 6]
                if chunk:[cite: 6]
                    f.write(chunk)[cite: 6]

        folder_id = get_or_create_folder("MyCloudPlayer", req.access_token)[cite: 6]

        # --- UPDATED 2-STEP RAW UPLOAD LOGIC ---
        
        # 1. Upload the raw audio data directly
        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=media"
        upload_headers = {
            "Authorization": f"Bearer {req.access_token}",
            "Content-Type": "audio/mpeg"
        }
        
        with open(file_path, "rb") as media_file:
            upload_res = requests.post(upload_url, headers=upload_headers, data=media_file)
            
        if upload_res.status_code not in (200, 201):
            if os.path.exists(file_path):[cite: 6]
                os.remove(file_path)[cite: 6]
            raise HTTPException(status_code=upload_res.status_code, detail=upload_res.text)
            
        file_id = upload_res.json().get("id")

        # 2. Update the file name and move it into the MyCloudPlayer folder
        metadata_url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        metadata_headers = {
            "Authorization": f"Bearer {req.access_token}",
            "Content-Type": "application/json"
        }
        metadata = {
            'name': f"{video_title}.mp3",
            'parents': [folder_id]
        }
        
        patch_res = requests.patch(metadata_url, headers=metadata_headers, json=metadata)

        if os.path.exists(file_path):[cite: 6]
            os.remove(file_path)[cite: 6]

        if patch_res.status_code in (200, 201):
            return {"status": "success", "file": patch_res.json()}
        else:
            raise HTTPException(status_code=patch_res.status_code, detail=patch_res.text)

    except Exception as e:[cite: 6]
        if 'file_path' in locals() and os.path.exists(file_path):[cite: 6]
            os.remove(file_path)[cite: 6]
        raise HTTPException(status_code=500, detail=str(e))[cite: 6]