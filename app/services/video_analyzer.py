import cv2
import numpy as np
from app.services.object_detection import object_detection_service
from app.db import database

class VideoAnalyzer:
    def __init__(self, video_path, video_id):
        self.video_path = video_path
        self.video_id = video_id
        self.cap = cv2.VideoCapture(self.video_path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

    async def analyze_frame(self, frame_number):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = self.cap.read()
        if not ret:
            return None

        detections = object_detection_service.detect_objects(frame)
        objects = object_detection_service.process_detections(
            detections, class_names=['background', 'person', 'car', ...])

        return {
            'timestamp': frame_number / self.fps,
            'objects': objects
        }

    async def analyze_video(self, interval=1):
        for frame_number in range(0, self.frame_count, int(self.fps * interval)):
            frame_result = await self.analyze_frame(frame_number)
            if frame_result:
                await self.save_frame_analysis(frame_result)

    async def save_frame_analysis(self, frame_analysis):
        query = """
        INSERT INTO video_analysis (video_id, timestamp, objects)
        VALUES (:video_id, :timestamp, :objects)
        """
        values = {
            'video_id': self.video_id,
            'timestamp': frame_analysis['timestamp'],
            'objects': json.dumps(frame_analysis['objects'])
        }
        await database.execute(query=query, values=values)

    def __del__(self):
        if self.cap:
            self.cap.release()


video_analyzer = VideoAnalyzer
