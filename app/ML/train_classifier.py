# %%
# train_classifier.py
from sklearn.datasets import make_classification
from sklearn.ensemble import RandomForestClassifier
import joblib
from transformers import BertTokenizer, BertModel
import torch

# Load models and tokenizer
bert_tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
bert_model = BertModel.from_pretrained('bert-base-uncased')

# Function to extract features using BERT


def extract_features(text, tokenizer, model):
    inputs = tokenizer(text, return_tensors='pt',
                       padding=True, truncation=True, max_length=512)
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state.mean(dim=1).squeeze().numpy()


# Generate some example texts for training
texts = [
    "This is a sample text for training.",
    "Another example of text for training the classifier.",
    "Machine learning models can be tricky.",
    "Artificial intelligence is the future.",
    "Random forests are a type of ensemble learning method."
]

# Extract features for each text
X_train = [extract_features(text, bert_tokenizer, bert_model)
           for text in texts]
y_train = [0, 0, 1, 1, 1]  # Example labels

# Train the classifier
classifier = RandomForestClassifier(n_estimators=100, random_state=42)
classifier.fit(X_train, y_train)

# Save the trained model
joblib.dump(classifier, 'classifier.pkl')

# %%
