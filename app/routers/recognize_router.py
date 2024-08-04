# from fastapi import APIRouter, HTTPException
# from pydantic import BaseModel
# import cv2
# import numpy as np
# import base64
# import tensorflow as tf
# from app.services.object_detection import object_detection_service
# from app.services.object_info import object_info_service

# router = APIRouter()


# class ImageData(BaseModel):
#     imageData: str


# model = tf.saved_model.load('app/models/ml/object_detection')


# @router.post("/")
# async def recognize_object(data: ImageData):
#     try:
#         img_data = base64.b64decode(data.imageData.split(',')[1])
#         nparr = np.frombuffer(img_data, np.uint8)
#         img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

#         detections = object_detection_service.detect_objects(img)
#         results = object_detection_service.process_detections(detections, class_names=[
#                                                               'background', 'person', 'car', ...])  # Add your class names here

#         return {"objects": results}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/info/{object_name}")
# async def get_object_info(object_name: str):
#     try:
#         info = await object_info_service.get_object_info(object_name)
#         return info
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
