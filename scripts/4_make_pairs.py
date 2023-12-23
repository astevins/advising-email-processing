import pandas as pd
import configparser
from tqdm import tqdm 
from shared_defns import *

# Constants
config = configparser.ConfigParser()
config.read('config.ini')
ENCODING = config['global']['ENCODING']
        
def from_csv(in_path,out_path):
    """
    Convert conversations to question-answer pairs
    """
    emails_df = pd.read_csv(in_path,index_col=0,encoding=ENCODING)
    print(f"Loaded {emails_df.shape[0]} emails")
    result = []
    
    print(f"Processing {len(emails_df.groupby('conversation'))} conversations")
    for conversation, group in tqdm(emails_df.groupby('conversation')):
        if group.iloc[0]['from'] not in [1,4]:
            # Skipping conversation not started by student
            continue
        
        i = 0
        question = ''
        answer = ''
        for row in group.itertuples(index=False):
            if type(row.body) != str or row.body == 'nan' or len(row.body.strip()) == 0: continue
            if row._5 == 1:
                # message from student
                if len(answer) > 0:
                    if len(question) > 0 and len(answer) > 0:
                        result.append({'conversation': conversation, 'turn': i, 'question': question, 'answer': answer})
                    question = ''
                    answer = ''
                    i += 1
                question = row.body
            elif row._5 == 2:
                # message from advising
                answer = row.body
        
        if len(question) > 0 and len(answer) > 0:
            result.append({'conversation': conversation, 'turn': i, 'question': question, 'answer': answer})
    
    result_df = pd.DataFrame.from_dict(result)
    result_df.to_csv(out_path,encoding=ENCODING)
    print(f"Saved file with {result_df.shape[0]} pairs")

def main():
    in_path = get_filepath(config, 'extract_contents', 'OUT_FILE')
    out_path = get_filepath(config, 'make_pairs', 'OUT_FILE')
    from_csv(in_path,out_path)

if __name__ == '__main__':
    main()