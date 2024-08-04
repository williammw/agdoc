# import tensorflow as tf
# import numpy as np

# class ObjectDetectionService:
#     def __init__(self, model_path):
#         self.model = tf.saved_model.load(model_path)

#     def detect_objects(self, image):
#         input_tensor = tf.convert_to_tensor(image)
#         input_tensor = input_tensor[tf.newaxis, ...]
#         detections = self.model(input_tensor)
        
#         num_detections = int(detections.pop('num_detections'))
#         detections = {key: value[0, :num_detections].numpy() 
#                       for key, value in detections.items()}
#         detections['num_detections'] = num_detections
#         detections['detection_classes'] = detections['detection_classes'].astype(np.int64)
        
#         return detections

#     def process_detections(self, detections, class_names, min_score=0.5):
#         results = []
#         for i in range(detections['num_detections']):
#             if detections['detection_scores'][i] > min_score:
#                 class_id = int(detections['detection_classes'][i])
#                 class_name = class_names[class_id] if class_id < len(class_names) else 'Unknown'
#                 confidence = float(detections['detection_scores'][i])
#                 bbox = detections['detection_boxes'][i].tolist()
#                 results.append({
#                     'name': class_name,
#                     'confidence': confidence,
#                     'bbox': bbox
#                 })
#         return results


# object_detection_service = ObjectDetectionService(
#     'app/models/ml/object_detection')
