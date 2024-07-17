# cdn_router.py
from fastapi import APIRouter, Depends, HTTPException, Header
import uuid
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Header, Request
from databases import Database
from app.dependencies import get_database, get_current_user, verify_token
import boto3
import os

router = APIRouter()

# Initialize the boto3 client for Cloudflare R2
r2_client = boto3.client(
    's3',
    endpoint_url=os.getenv('R2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
    region_name='weur'
)

bucket_name = 'umami'
allowed_mime_types = ['image/jpeg', 'image/png',
                      'image/gif', 'video/mp4', 'video/mpeg']


@router.get("/list-objects/")
async def list_objects(database: Database = Depends(get_database), authorization: str = Header(...)):
    token = authorization.split(" ")[1]
    decoded_token = verify_token(token)
    user_id = decoded_token['uid']

    try:
        # Query the database for objects belonging to the user
        query = "SELECT id, filename, url, content_type, r2_object_key, is_public FROM cloudflare_r2_data WHERE user_id = :user_id"
        values = {"user_id": user_id}
        objects = await database.fetch_all(query=query, values=values)

        if objects:
            return {"objects": objects}
        else:
            return {"message": "No objects found for this user."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-image-cloudflare/")
async def upload_to_cloudflare(file: UploadFile = File(...), database: Database = Depends(get_database), authorization: str = Header(...)):
    token = authorization.split(" ")[1]
    decoded_token = verify_token(token)
    user_id = decoded_token['uid']

    headers = {
        "Authorization": f"Bearer {os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')}",
    }
    url = f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/images/v1"

    files = {
        'file': (file.filename, await file.read(), file.content_type),
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, files=files)
        response.raise_for_status()

    image_data = response.json()

    try:
        url = image_data.get("result", {}).get("variants", [])[0]
    except IndexError:
        raise HTTPException(
            status_code=500, detail="URL not returned from Cloudflare")

    query = """
    INSERT INTO cloudflare_images (filename, url, content_type, cloudflare_id, user_id)
    VALUES (:filename, :url, :content_type, :cloudflare_id, :user_id)
    """
    values = {
        "filename": file.filename,
        "url": url,
        "content_type": file.content_type,
        "cloudflare_id": image_data.get("result", {}).get("id"),
        "user_id": user_id,
    }

    await database.execute(query=query, values=values)

    return {"message": "Image uploaded and metadata saved successfully", "data": image_data}


@router.post("/upload-image-r2/")
async def upload_to_r2(file: UploadFile = File(...), database: Database = Depends(get_database), authorization: str = Header(...)):
    token = authorization.split(" ")[1]
    decoded_token = verify_token(token)
    user_id = decoded_token['uid']

    # Validate file type
    mime_type = file.content_type
    if mime_type not in allowed_mime_types:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # Generate a unique file name to avoid conflicts
    file_key = f"{user_id}/images/{file.filename}"

    try:
        # Upload file to R2
        r2_client.upload_fileobj(
            file.file,
            bucket_name,
            file_key,
            ExtraArgs={"ContentType": file.content_type, "ACL": "public-read"}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not upload the image to Cloudflare R2: {str(e)}"
        )

    # Construct the file URL
    file_url = f"https://{os.getenv('R2_DEV_URL')}/{file_key.replace('/', '%2F')}"

    # Proceed with database insertion
    query = """
    INSERT INTO cloudflare_r2_data (filename, url, content_type, r2_object_key, user_id, is_public)
    VALUES (:filename, :url, :content_type, :r2_object_key, :user_id, :is_public)
    """
    values = {
        "filename": file.filename,
        "url": file_url,
        "content_type": file.content_type,
        "r2_object_key": file_key,
        "user_id": user_id,
        "is_public": False  # Default to private
    }

    try:
        await database.execute(query=query, values=values)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to insert metadata into the database: {str(exc)}"
        )

    return {"message": "Image uploaded to Cloudflare R2 and metadata saved successfully", "url": file_url}


@router.post("/toggle-public-status/")
async def toggle_public_status(request: Request, database: Database = Depends(get_database), authorization: str = Header(...)):
    token = authorization.split(" ")[1]
    decoded_token = verify_token(token)
    user_id = decoded_token['uid']

    data = await request.json()
    file_id = data.get("file_id")
    is_public = data.get("is_public")

    if file_id is None or is_public is None:
        raise HTTPException(status_code=400, detail="Invalid input")

    # Fetch the file record
    query = "SELECT r2_object_key FROM cloudflare_r2_data WHERE id = :file_id AND user_id = :user_id"
    file_record = await database.fetch_one(query=query, values={"file_id": file_id, "user_id": user_id})

    if file_record is None:
        raise HTTPException(status_code=404, detail="File not found")

    # Update the public status in the database
    query = "UPDATE cloudflare_r2_data SET is_public = :is_public WHERE id = :file_id AND user_id = :user_id"
    await database.execute(query=query, values={"is_public": is_public, "file_id": file_id, "user_id": user_id})

    # Update the access control in Cloudflare R2
    file_key = file_record["r2_object_key"]
    acl = "public-read" if is_public else "private"

    try:
        r2_client.put_object_acl(
            Bucket=bucket_name,
            Key=file_key,
            ACL=acl
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not update ACL for Cloudflare R2: {str(e)}"
        )

    return {"message": "File public status updated successfully"}


@router.post("/upload-avatar/")
async def upload_avatar(file: UploadFile = File(...), current_user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    print("Current user: entry", current_user)
    try:
        print("Current user: try", current_user)
        # Generate a unique file name
        file_extension = os.path.splitext(file.filename)[1]
        # file_key = f"{user_id}/images/{file.filename}"
        unique_filename = f"{current_user['uid']}/avatar/{file_extension}"

        # Upload file to R2
        r2_client.upload_fileobj(
            file.file,
            bucket_name,
            unique_filename,
            ExtraArgs={"ContentType": file.content_type, "ACL": "public-read"}
        )

        # Construct the file URL
        file_url = f"https://{os.getenv('R2_DEV_URL')}/{unique_filename}"

        # Update database with new avatar URL
        query = "UPDATE users SET avatar_url = :avatar_url WHERE id = :id"
        values = {"id": current_user['uid'], "avatar_url": file_url}
        await db.execute(query=query, values=values)

        return {"message": "Avatar uploaded successfully", "url": file_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-livestream")
async def create_livestream(
    database: Database = Depends(get_database),
    authorization: str = Header(...)
):
    try:
        token = authorization.split(" ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']
    except Exception as e:
        raise HTTPException(
            status_code=401, detail="Invalid authorization token")

    headers = {
        "Authorization": f"Bearer {os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')}",
        "Content-Type": "application/json"
    }
    url = f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/stream/live_inputs"

    payload = {
        "meta": {"name": f"Livestream for user {user_id}"},
        "recording": {"mode": "automatic"}
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail="Failed to create livestream with Cloudflare")
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"An error occurred while creating the livestream: {str(exc)}")

    try:
        stream_data = response.json()
        # print("Cloudflare API Response:", stream_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail="Invalid JSON response from Cloudflare")

    result = stream_data.get('result', {})
    print("!!!   ********  Cloudflare API Result:", result)
    cloudflare_id = result.get('uid', '')
    rtmps_url = result.get('rtmps', {}).get('url', '')
    stream_key = result.get('rtmps', {}).get('streamKey', '')
    webrtc_url = result.get('webRTC', {}).get('url', '')

    if not all([cloudflare_id, rtmps_url, stream_key, webrtc_url]):
        raise HTTPException(
            status_code=500, detail="Missing required fields in Cloudflare response")

    query = """
    INSERT INTO livestreams (id, user_id, stream_key, rtmps_url, cloudflare_id, status, webrtc_url)
    VALUES (:id, :user_id, :stream_key, :rtmps_url, :cloudflare_id, :status, :webrtc_url)
    """
    values = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "stream_key": stream_key,
        "rtmps_url": rtmps_url,
        "cloudflare_id": cloudflare_id,
        "status": "created",
        "webrtc_url": webrtc_url
    }

    try:
        await database.execute(query=query, values=values)
    except Exception as e:
        print(f"Database error: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to save livestream data to database")

    return {
        "streamKey": stream_key,
        "rtmpsUrl": rtmps_url,
        "webrtcUrl": webrtc_url,
        "cloudflareId": cloudflare_id
    }


@router.get("/livestream-playback/{cloudflare_id}")
async def get_livestream_playback(
    cloudflare_id: str,
    authorization: str = Header(...)
):
    token = authorization.split(" ")[1]
    decoded_token = verify_token(token)

    headers = {
        "Authorization": f"Bearer {os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')}",
    }
    url = f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/stream/live_inputs/{cloudflare_id}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()

    data = response.json()
    playback_url = data['result']['playback']['hls']
    return {"playback_url": playback_url}


@router.get("/stream-status/{stream_id}")
async def get_stream_status(stream_id: str, authorization: str = Header(...)):
    try:
        token = authorization.split(" ")[1]
        decoded_token = verify_token(token)
        user_id = decoded_token['uid']

        account_id = os.getenv('CLOUDFLARE_ACCOUNT_ID')
        api_token = os.getenv('CLOUDFLARE_STREAM_AND_IMAGES_API_TOKEN')

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/stream/live_inputs/{stream_id}"
        headers = {
            "Authorization": f"Bearer {api_token}",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

            data = response.json()
            # Add this line
            print(f"Cloudflare API response for stream {stream_id}: {data}")
            is_live = data.get('result', {}).get('status') == 'live'

            # Add more detailed logging
            print(
                f"Stream {stream_id} status: {data.get('result', {}).get('status')}")
            print(f"Is live: {is_live}")

        return {"isLive": is_live}
    except httpx.HTTPError as exc:
        # Add this line
        print(f"HTTP Exception for stream {stream_id}: {str(exc)}")
        raise HTTPException(status_code=exc.response.status_code,
                            detail=f"HTTP Exception: {str(exc)}")
    except Exception as exc:
        # Add this line
        print(f"General Exception for stream {stream_id}: {str(exc)}")
        raise HTTPException(
            status_code=500, detail=f"An error occurred: {str(exc)}")



