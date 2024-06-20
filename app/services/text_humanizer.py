import nltk
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.corpus import wordnet
from transformers import T5Tokenizer, T5ForConditionalGeneration
from sentence_transformers import SentenceTransformer, util
import sentencepiece
import os
nltk.download('punkt')
nltk.download('wordnet')
model_path = os.path.join(os.path.dirname(__file__), 'fine_tuned_model')

tokenizer = T5Tokenizer.from_pretrained(model_path)
model = T5ForConditionalGeneration.from_pretrained(model_path)
sentence_bert_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')


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
    sentences = sent_tokenize(" ".join(tokens))
    return sentences


def rephrase_with_model(text):
    input_ids = tokenizer.encode(
        f"paraphrase: {text}", return_tensors="pt", max_length=512, truncation=True)
    outputs = model.generate(input_ids, max_length=512,
                             num_beams=4, early_stopping=True)
    paraphrased_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return paraphrased_text


def rephrase_with_sentence_bert(text):
    sentences = sent_tokenize(text)
    paraphrased_sentences = []
    for sentence in sentences:
        paraphrases = sentence_bert_model.encode([sentence])
        paraphrased_sentence = util.paraphrase_mining(
            paraphrases, corpus=[sentence])
        paraphrased_sentences.append(paraphrased_sentence[0][0])
    return " ".join(paraphrased_sentences)


def humanize_text(text):
    tokens = preprocess_text(text)
    tokens = replace_with_synonyms(tokens)
    sentences = adjust_sentence_structure(tokens)
    intermediate_text = " ".join(sentences)
    humanized_text = rephrase_with_model(intermediate_text)
    return humanized_text
