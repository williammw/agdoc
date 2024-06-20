# %%
from transformers import T5ForConditionalGeneration, T5Tokenizer, Trainer, TrainingArguments
import torch

# Initialize the model and tokenizer
model = T5ForConditionalGeneration.from_pretrained('t5-small')
tokenizer = T5Tokenizer.from_pretrained('t5-small')

# Example dataset for fine-tuning
train_data = [
    {"text": "original text 1", "summary": "humanized text 1"},
    {"text": "original text 2", "summary": "humanized text 2"},
    # Add more examples
]


class CustomDataset(torch.utils.data.Dataset):
    def __init__(self, data, tokenizer, max_len):
        self.data = data
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]
        encoding = self.tokenizer(
            item['text'], max_length=self.max_len, padding='max_length', truncation=True, return_tensors='pt'
        )
        summary_encoding = self.tokenizer(
            item['summary'], max_length=self.max_len, padding='max_length', truncation=True, return_tensors='pt'
        )
        labels = summary_encoding['input_ids']
        labels[labels == self.tokenizer.pad_token_id] = -100
        return {'input_ids': encoding['input_ids'].flatten(), 'attention_mask': encoding['attention_mask'].flatten(), 'labels': labels.flatten()}


train_dataset = CustomDataset(train_data, tokenizer, max_len=512)

# Define training arguments
training_args = TrainingArguments(
    output_dir='./results',
    num_train_epochs=3,
    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,
    warmup_steps=500,
    weight_decay=0.01,
    logging_dir='./logs',
    logging_steps=10,
)

# Initialize the Trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=None,
)

# Fine-tune the model
trainer.train()

# Save the fine-tuned model
model.save_pretrained('./fine_tuned_model')
tokenizer.save_pretrained('./fine_tuned_model')

# %%
