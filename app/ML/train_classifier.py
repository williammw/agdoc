# %%
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split, GridSearchCV
from transformers import BertTokenizer, BertModel
import torch

# Load your dataset
# Assume you have a CSV file with columns 'text' and 'label' (0 for human-written, 1 for AI-generated)
data = pd.read_csv('path_to_your_dataset.csv')

# Preprocess the text data


def preprocess_text(text):
    tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
    model = BertModel.from_pretrained('bert-base-uncased')
    inputs = tokenizer(text, return_tensors='pt',
                       padding=True, truncation=True, max_length=512)
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state.mean(dim=1).squeeze().numpy()


data['features'] = data['text'].apply(preprocess_text)

# Split the data
X_train, X_test, y_train, y_test = train_test_split(
    data['features'].tolist(), data['label'], test_size=0.2, random_state=42)

# Train the classifier
classifier = RandomForestClassifier()

# Hyperparameter tuning
param_grid = {
    'n_estimators': [100, 200, 300],
    'max_depth': [10, 20, 30],
    'min_samples_split': [2, 5, 10],
    'min_samples_leaf': [1, 2, 4]
}
grid_search = GridSearchCV(
    estimator=classifier, param_grid=param_grid, cv=3, n_jobs=-1, verbose=2)
grid_search.fit(X_train, y_train)

# Save the trained model
joblib.dump(grid_search.best_estimator_, 'classifier.pkl')
