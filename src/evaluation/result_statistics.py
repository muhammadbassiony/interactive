import torch
import os
import math
from interactive_LM.src.evaluation import ngram
from spacy.lang.en import English
import nltk
import sys

def sample_statistics(selected_topic_idx, generated_sent, top_index_im, idx2word_freq, selected_word_idx=None):
    def highlight_words(word_nn, generated_sent, topic_l2_word_d2_count_t, exact_count):
        def find_all(a_str, sub):
            start = 0
            while True:
                start = a_str.find(sub, start)
                if start == -1: return
                yield start
                start += len(sub)

        for m_start in find_all(generated_sent, word_nn):
            start = m_start
            end = m_start + len(word_nn)
            if not (end < len(generated_sent) - 1 and generated_sent[end+1].isalpha()) or (start != 0 and generated_sent[start-1].isalpha()):
                if word_nn not in exact_count:
                    exact_count[word_nn] = 0
                exact_count[word_nn] += 1
            if not (end < len(generated_sent) - 1 and generated_sent[end+1] != ' ' and start != 0 and generated_sent[start-1] != ' '): 
                if word_nn not in topic_l2_word_d2_count_t:
                    topic_l2_word_d2_count_t[word_nn] = 0
                topic_l2_word_d2_count_t[word_nn] += 1
        return generated_sent
        
    num_selected = len(selected_topic_idx)
    top_k = top_index_im.size(0)
    topic_l2_word_d2_count = [{} for t in range(num_selected)]
    exact_count = [{} for t in range(num_selected)]
    for t in range(num_selected):
        topic_idx = selected_topic_idx[t]
        for k in range(top_k):
            word_nn = idx2word_freq[top_index_im[k,topic_idx].item()][0]
            generated_sent = highlight_words(word_nn, generated_sent, topic_l2_word_d2_count[t], exact_count[t])

    num_token_hit = [0,0]
    num_word_type_hit = [0,0]
    num_topic_hit = [0,0]
    for t in range(num_selected):
        if len(topic_l2_word_d2_count[t]) == 0:
            continue
        topic_idx = selected_topic_idx[t]
        num_topic_hit[0] += 1
        for each in topic_l2_word_d2_count[t]:
            num_word_type_hit[0] += 1
            num_token_hit[0] += topic_l2_word_d2_count[t][each]
    
    for t in range(num_selected):
        if len(exact_count[t]) == 0:
            continue
        topic_idx = selected_topic_idx[t]
        num_topic_hit[1] += 1
        for each in exact_count[t]:
            num_word_type_hit[1] += 1
            num_token_hit[1] += exact_count[t][each]

    return num_token_hit, num_word_type_hit, num_topic_hit

def perplexity(model, context, generated_sent):
    feature = context
    feature_generated = generated_sent
    device = next(model.parameters()).device
    feature_empty = torch.tensor((), device = device, dtype=torch.long).new_full((feature.shape[0], feature.shape[1]), -100)
    feature = torch.cat((feature, feature_generated), dim=1)
    feature_generated = torch.cat((feature_empty, feature_generated), dim=1)
    outputs_GPT2LMHeadModel= model(feature, labels=feature_generated)
    return outputs_GPT2LMHeadModel[0]

def eval_using_BLEU(generated_sentence, word_raw_list_i_j, word_raw_rest_list_i_j, spacy_nlp):
    if len(word_raw_list_i_j) <= 1:
        return -1, -1, []
    future_window_size = 25
    if len(word_raw_rest_list_i_j) <= future_window_size + 1:
        return -1, -1, []

    doc = spacy_nlp(generated_sentence)
    gen_list = []
    for tok in doc:
        gen_list.append(tok.text)
    #print(word_raw_list_i_j[:-1])
    #print(word_raw_rest_list_i_j[1:future_window_size + 1])
    #print(gen_list)
    sys.stdout.flush()
    cc = nltk.translate.bleu_score.SmoothingFunction()
    context_BLEU = nltk.translate.bleu_score.sentence_bleu([word_raw_list_i_j[:-1]], gen_list, weights = (0.5, 0.5), smoothing_function=cc.method3)
    BLEU = nltk.translate.bleu_score.sentence_bleu([word_raw_rest_list_i_j[1:future_window_size + 1]], gen_list, weights = (0.5, 0.5), smoothing_function=cc.method3)
    return BLEU, context_BLEU, gen_list

class result_statistics:

    def __init__(self, model):
        self.model_results = {}
        #self.model_results["time_count"] = 0
        self.gpt2_model = model
        self.nlp = English()

    def add_model(self, model_name):
        self.model_results[model_name] = {}
        self.model_results[model_name]["batch count"] = 0
        self.model_results[model_name]["count"] = 0
        self.model_results[model_name]["BLEU_count"] = 0
        self.model_results[model_name]["BLEU_count_arr"] = []
        self.model_results[model_name]["BLEU"] = 0
        self.model_results[model_name]["BLEU_arr"] = []
        self.model_results[model_name]["context_len_arr"] = []
        self.model_results[model_name]["context BLEU"] = 0
        self.model_results[model_name]["gen_list_temp"] = []
        self.model_results[model_name]["self BLEU count"] = 0
        self.model_results[model_name]["self BLEU"] = 0
        self.model_results[model_name]["token hit"] = 0
        self.model_results[model_name]["word type hit"] = 0
        self.model_results[model_name]["topic hit"] = 0
        self.model_results[model_name]["exact token hit"] = 0
        self.model_results[model_name]["exact word type hit"] = 0
        self.model_results[model_name]["exact topic hit"] = 0
        self.model_results[model_name]["perplexity"] = 0
        self.model_results[model_name]["ngram"] = ngram()
        self.model_results[model_name]["unigram"] = 0
        self.model_results[model_name]["bigram"] = 0
        self.model_results[model_name]["time_sum"] = 0
        self.model_results[model_name]["time_count"] = 0

    def update_self_BLEU(self, model_name):
        count = 0
        gen_list_temp = self.model_results[model_name]["gen_list_temp"]
        num_sent_gen = len(gen_list_temp)
        cc = nltk.translate.bleu_score.SmoothingFunction()
        for i in range(num_sent_gen):
            for j in range(i+1,num_sent_gen):
                self_BLEU = nltk.translate.bleu_score.sentence_bleu([gen_list_temp[i]],gen_list_temp[j], weights = (0.5, 0.5), smoothing_function=cc.method3)
                self.model_results[model_name]["self BLEU count"] += 1
                self.model_results[model_name]["self BLEU"] += self_BLEU
        self.model_results[model_name]["gen_list_temp"] = []
        

    def update(self, model_name, sentence, context, selected_topic_idx, top_index, idx2word_freq, tokenizer, word_raw_list_i_j=None, word_raw_rest_list_i_j=None, j = None):
        generated_sent = tokenizer.convert_tokens_to_string( [tokenizer._convert_id_to_token(x) for x in sentence.tolist()] )
        num_token_hit, num_word_type_hit, num_topic_hit = sample_statistics(selected_topic_idx, generated_sent, top_index, idx2word_freq)
        log_perplexity = perplexity(self.gpt2_model, context.unsqueeze(0), sentence.unsqueeze(0))
        if word_raw_list_i_j is not None:
            #context_sents = tokenizer.convert_tokens_to_string( [tokenizer._convert_id_to_token(x) for x in context.tolist()] )
            while j >= len(self.model_results[model_name]['BLEU_count_arr']):
                self.model_results[model_name]['BLEU_count_arr'].append(1e-15)
                self.model_results[model_name]['BLEU_arr'].append(0)
                self.model_results[model_name]['context_len_arr'].append(0)
            BLEU, context_BLEU, gen_list = eval_using_BLEU(generated_sent, word_raw_list_i_j, word_raw_rest_list_i_j, self.nlp)
            if BLEU != -1:
                self.model_results[model_name]["gen_list_temp"].append(gen_list)
                self.model_results[model_name]["BLEU"] += BLEU
                self.model_results[model_name]["context BLEU"] += context_BLEU
                self.model_results[model_name]["BLEU_count"] += 1
                self.model_results[model_name]['BLEU_count_arr'][j] += 1
                self.model_results[model_name]['BLEU_arr'][j] += BLEU
                self.model_results[model_name]['context_len_arr'][j] += len(word_raw_list_i_j[:-1])
        self.model_results[model_name]["count"] += 1
        self.model_results[model_name]["token hit"] += num_token_hit[0]
        self.model_results[model_name]["word type hit"] += num_word_type_hit[0]
        self.model_results[model_name]["topic hit"] += num_topic_hit[0]
        self.model_results[model_name]["exact token hit"] += num_token_hit[1]
        self.model_results[model_name]["exact word type hit"] += num_word_type_hit[1]
        self.model_results[model_name]["exact topic hit"] += num_topic_hit[1]
        self.model_results[model_name]["perplexity"] += log_perplexity
        self.model_results[model_name]["ngram"].add(generated_sent)

    
    def renew_ngram(self):
        for model_name, model in self.model_results.items():
            model["batch count"] += 1
            unigram, bigram = model["ngram"].diversity_n()
            #print(model["ngram"].diversity_n())
            model["unigram"] += unigram
            model["bigram"] += bigram
            model["ngram"] = ngram()
            #print(model["ngram"].diversity_n())


    def print(self):
        for model_name, model in self.model_results.items():
            print(model_name, "count: ", model["count"])
            print(model_name, "BLEU count: ", model["BLEU_count"])
            print(model_name, "batch count: ", model["batch count"])
            print(model_name, "BLEU: ", model["BLEU"] / model["BLEU_count"])
            print(model_name + " " + "BLEU_arr: "+ str( [model["BLEU_arr"][x] / model["BLEU_count_arr"][x] if model["BLEU_count_arr"][x] > 0 else 0 for x in range(len(model["BLEU_count_arr"]))] ) )
            print(model_name + " " + "context_len_arr: "+ str( [model["context_len_arr"][x] / model["BLEU_count_arr"][x] if model["BLEU_count_arr"][x] > 0 else 0 for x in range(len(model["BLEU_count_arr"]))] ) )
            print(model_name, "self BLEU: ", model["self BLEU"] / (1e-13+model["self BLEU count"]))
            print(model_name, "context BLEU: ", model["context BLEU"] / model["BLEU_count"])
            print(model_name + " " + "BLEU Diff: " + str(model["BLEU"] / model["BLEU_count"] - model["context BLEU"] / model["BLEU_count"] ) )
            print(model_name, "token hit: ", model["token hit"] / model["count"])
            print(model_name, "exact token hit: ", model["exact token hit"] / model["count"])
            print(model_name, "word type hit: ", model["word type hit"] / model["count"])
            print(model_name, "exact word type hit: ", model["exact word type hit"] / model["count"])
            print(model_name, "topic hit: ", model["topic hit"] / model["count"])
            print(model_name, "exact topic hit: ", model["exact topic hit"] / model["count"])
            print(model_name, "perplexity: ", math.exp(model["perplexity"] / model["count"]))
            print(model_name, "unigram: ", model["unigram"] / model["batch count"])
            print(model_name, "bigram: ", model["bigram"] / model["batch count"])
            if model['time_count'] > 0:
                print(model_name, "running time: ", model["time_sum"] / model['time_count'])
            print()



    def generate_report(self, outf):
        outf.write('Reports: \n')
        for model_name, model in self.model_results.items():
            outf.write(model_name + " " + "count: " + str(model["count"]) + '\n')
            outf.write(model_name + " " + "BLEU count: " + str(model["BLEU_count"]) + '\n')
            outf.write(model_name + " " + "batch count: " + str(model["batch count"]) + '\n')
            outf.write(model_name + " " + "BLEU: " + str(model["BLEU"] / model["BLEU_count"]) + '\n')
            outf.write(model_name + " " + "BLEU_arr: "+ str( [model["BLEU_arr"][x] / model["BLEU_count_arr"][x] if model["BLEU_count_arr"][x] > 0 else 0 for x in range(len(model["BLEU_count_arr"]))] ) + '\n')
            outf.write(model_name + " " + "context_len_arr: "+ str( [model["context_len_arr"][x] / model["BLEU_count_arr"][x] if model["BLEU_count_arr"][x] > 0 else 0 for x in range(len(model["BLEU_count_arr"]))] ) + '\n')
            outf.write(model_name + " " + "self BLEU: " + str(model["self BLEU"] / (1e-13+ model["self BLEU count"])) + '\n')
            outf.write(model_name + " " + "context BLEU: " + str(model["context BLEU"] / model["BLEU_count"]) + '\n')
            outf.write(model_name + " " + "BLEU Diff: " + str(model["BLEU"] / model["BLEU_count"] - model["context BLEU"] / model["BLEU_count"] ) + '\n')
            outf.write(model_name + " " + "token hit: " + str(model["token hit"] / model["count"]) + '\n')
            outf.write(model_name + " " + "exact token hit: " + str(model["exact token hit"] / model["count"]) + '\n')
            outf.write(model_name + " " + "word type hit: " + str(model["word type hit"] / model["count"]) + '\n')
            outf.write(model_name + " " + "exact word type hit: " + str(model["exact word type hit"] / model["count"]) + '\n')
            outf.write(model_name + " " + "topic hit: " + str(model["topic hit"] / model["count"]) + '\n')
            outf.write(model_name + " " + "exact topic hit: " + str(model["exact topic hit"] / model["count"]) + '\n')
            outf.write(model_name + " " + "perplexity: " + str(math.exp(model["perplexity"] / model["count"])) + '\n')
            outf.write(model_name + " " + "unigram: " + str(model["unigram"] / model["batch count"]) + '\n')
            outf.write(model_name + " " + "bigram: " + str(model["bigram"] / model["batch count"]) + '\n')
            if model['time_count'] > 0:
                outf.write(model_name + " " + "running time: " + str(model["time_sum"] / model['time_count']) + '\n')
            outf.write('\n')
    

