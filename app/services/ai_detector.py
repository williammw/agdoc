import joblib
import os
import torch
from transformers import BertTokenizer, BertModel

# Load models and tokenizer
bert_tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
bert_model = BertModel.from_pretrained('bert-base-uncased')

# Load the pre-trained classifier
classifier_path = os.path.join(os.path.dirname(__file__), '../ML/classifier.pkl')
classifier = joblib.load(classifier_path)

def extract_features(text):
    inputs = bert_tokenizer(text, return_tensors='pt', padding=True, truncation=True, max_length=512)
    with torch.no_grad():
        outputs = bert_model(**inputs)
    return outputs.last_hidden_state.mean(dim=1).squeeze().numpy()

def detect_ai_text(text):
    features = extract_features(text)
    prediction = classifier.predict([features])
    return 'AI-Generated' if prediction == 1 else 'Human-Written'