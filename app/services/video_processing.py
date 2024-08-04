import cv2
import numpy as np
from app.services.object_detection import object_detection_service


class VideoProcessingService:
    @staticmethod
    async def process_video(video_path):
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        results = []

        # Process one frame per second
        for frame_number in range(0, frame_count, int(fps)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            if not ret:
                break

            detections = object_detection_service.detect_objects(frame)
            objects = object_detection_service.process_detections(
                detections, class_names=['background', 'person', 'car', ...])

            results.append({
                'timestamp': frame_number / fps,
                'objects': objects
            })

        cap.release()
        return results


video_processing_service = VideoProcessingService()
