import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import wordnet
from transformers import T5Tokenizer, T5ForConditionalGeneration
import sentencepiece

nltk.download('punkt')
nltk.download('wordnet')

tokenizer = T5Tokenizer.from_pretrained('t5-small')
model = T5ForConditionalGeneration.from_pretrained('t5-small')


def preprocess_text(text):
    text = text.lower()
    tokens = word_tokenize(text)
    return tokens


def replace_with_synonyms(tokens):
    new_tokens = []
    for token in tokens:
        synonyms = wordnet.synsets(token)
        if synonyms:
            synonym = synonyms[0].lemmas()[0].name()
            new_tokens.append(synonym)
        else:
            new_tokens.append(token)
    return new_tokens


def adjust_sentence_structure(tokens):
    # Placeholder function to adjust sentence structure
    return tokens


def rephrase_with_model(text):
    input_ids = tokenizer.encode(
        f"paraphrase: {text}", return_tensors="pt", max_length=512, truncation=True)
    outputs = model.generate(input_ids, max_length=512,
                             num_beams=4, early_stopping=True)
    paraphrased_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return paraphrased_text


def humanize_text(text):
    tokens = preprocess_text(text)
    tokens = replace_with_synonyms(tokens)
    tokens = adjust_sentence_structure(tokens)
    intermediate_text = " ".join(tokens)
    humanized_text = rephrase_with_model(intermediate_text)
    return humanized_text
