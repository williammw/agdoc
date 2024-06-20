# from fastapi import APIRouter, HTTPException
# from pydantic import BaseModel
# from app.services.text_humanizer import humanize_text
# from app.services.ai_detector import detect_ai_text

# # Define the router
# router = APIRouter()

# # Request and response models


# class TextRequest(BaseModel):
#     text: str


# class DetectionResponse(BaseModel):
#     result: str


# class HumanizeResponse(BaseModel):
#     humanized_text: str

# # AI text detection endpoint


# @router.post("/detect", response_model=DetectionResponse)
# async def detect_ai_text_endpoint(request: TextRequest):
#     try:
#         result = detect_ai_text(request.text)
#         return DetectionResponse(result=result)
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# # Humanize AI text endpoint


# @router.post("/humanize", response_model=HumanizeResponse)
# async def humanize_ai_text_endpoint(request: TextRequest):
#     try:
#         humanized_text = humanize_text(request.text)
#         return HumanizeResponse(humanized_text=humanized_text)
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
