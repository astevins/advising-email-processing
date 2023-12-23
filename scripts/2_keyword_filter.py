"""
Basic script to remove irrelevant emails from the emails csv
Removes emails about forms, applications, etc. that are out of scope
for the academic calendar question answering system
"""

import pandas as pd
import configparser
from shared_defns import *

# Constants
config = configparser.ConfigParser()
config.read('config.ini')
ENCODING = config['global']['ENCODING']
        
# Load keywords to remove
body_remove_keywords = header_remove_keywords = []

with open(get_filepath(config, 'keyword_filter', 'BODY_KW_FILE')) as file:
    body_remove_keywords = [line.rstrip() for line in file]
    
with open(get_filepath(config, 'keyword_filter', 'HEADER_KW_FILE')) as file:
    header_remove_keywords = [line.rstrip() for line in file]

# Predicates that match emails to remove
def keyword_in_text(text: str, keywords, lowercase:bool=True):
    if type(text) != str: return False
    use_text = text.lower() if lowercase else text
    return any([keyword in use_text for keyword in keywords])

# Matches emails containing header keywords   
def header_kw(conv_df): return any(conv_df['header'].apply(lambda x: keyword_in_text(x,header_remove_keywords)))

# Matches emails containing body keywords
def body_kw(conv_df): return any(conv_df['body'].apply(lambda x: keyword_in_text(x,body_remove_keywords,lowercase=False)))

# Matches email conversations that do not include a student
def no_student_in_convo(conv_df): return not (1 in conv_df['from'].values)

# Matches email conversations that include some sender that is not a student or advisor
def outside_ubc_in_convo(conv_df): return (3 in conv_df['from'].values)

predicates = [header_kw,body_kw,no_student_in_convo,outside_ubc_in_convo]
    
def simple_filter(df):
    """
    Performs a simple filter function to remove unwanted conversations from the dataset
    """
    remove_convo_ids = []
    
    for conversation,conv_df in df.groupby('conversation'):
        for predicate in predicates:
            if predicate(conv_df):
                remove_convo_ids.append(conversation)
                break
            
    filtered_df = df[~df['conversation'].isin(remove_convo_ids)]
    return filtered_df
     
def main():
    if eval(config['keyword_filter']['ENABLED']):
        in_path = get_filepath(config, 'download_emails', 'OUT_FILE')
        out_path = get_filepath(config, 'keyword_filter', 'OUT_FILE')
        df = pd.read_csv(in_path,index_col=0,encoding=ENCODING)
        df_filtered = simple_filter(df)
        df_filtered.to_csv(out_path,encoding=ENCODING)
        print(f"Done removing emails by kw, removed {df.shape[0] - df_filtered.shape[0]} entries")
    else:
        print("Removing emails by kw is disabled")

if __name__ == '__main__':
    main()