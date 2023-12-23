"""
Collects emails between students and advisors, strips personal information,
and saves to csv file. Doesn't perform any other preprocessing.

Main method to use: get_emails
"""
import re as re
import os
import win32com.client as client
import pandas as pd
import scrubadub, scrubadub_spacy
import warnings
from tqdm.auto import tqdm
from datetime import datetime
from mailparser_reply import EmailReplyParser
import dateparser
from typing import List, Tuple, Dict, Any, Optional
from shared_defns import *
import quotequail
import configparser

ubc_internal_addresses = internal_address_regex = None

# Constants
config = configparser.ConfigParser()
config.read('config.ini')
ENCODING = config['global']['ENCODING']
ADVISING_INBOX_NAME = config['download_emails']['ADVISING_INBOX_NAME']
ADVISING_NAME = config['download_emails']['ADVISING_NAME']
ADVISING_ADDRESS = config['download_emails']['ADVISING_ADDRESS']
SAVE_INTERVAL = int(config['download_emails']['SAVE_INTERVAL'])
MAIL_ITEM_CLASS = 43

# Suppress PytzUsageWarning, caused by pywin32
warnings.filterwarnings(
    "ignore",
    message="The localize method is no longer necessary, as this time zone supports the fold attribute",
)

# Initialize the data scrubber
class StudentInfoFilth(scrubadub.filth.Filth):
    type = 'student-info'

@scrubadub.detectors.register_detector
class StudentIDDetector(scrubadub.detectors.RegexDetector):
    """
    Filth detector for scrubadub, finds student ids
    Likely to cause some false positives
    """
    autoload = True
    name = 'student-id'
    regex = re.compile("(\D|\A)(\d{8}|\d{4}-\d{4}|\d{4}\s\d{4})(\D|\Z)")
    filth_cls = StudentInfoFilth
    
scrubber = scrubadub.Scrubber() # Includes all default detectors: email, phone, etc.
scrubber.remove_detector('url') # Don't scrub urls, they may be useful
scrubber._detectors["email"].at_matcher = "@" # Make the email scrubber more strict, otherwise we get false positives
scrubber.add_detector(scrubadub.detectors.DateOfBirthDetector)
person_name_detector = scrubadub_spacy.detectors.spacy.SpacyEntityDetector(named_entities=['PERSON'])
scrubber.add_detector(person_name_detector)

# Repository for parsed messages
class Messages:
    conversations: Dict[int, List[Dict]]
    conv_id: int
    prev_loaded_dates: Tuple[int,int]
    first_msg_dict: Dict[str, Dict]

    def __init__(self) -> None:
        self.conversations = {}
        self.conv_idx = -1
        self.prev_loaded_dates = None
        self.first_msg_dict = {}

    def new_conversation(self):
        """
        Start a new conversation
        Future calls to add_message will append messages to this conversation
        """
        self.conv_idx += 1
        self.conversations[self.conv_idx] = []
        
    def add_message(self, date, _from: EmailAddress, to: EmailAddress, subject: str, body: str, folder_path: str):
        """
        Add a message to the repository
        If the body and header is empty, just skips the message
        """

        if (not subject or subject.strip() == '') and (not body or body.strip() == ''):
            return # skip the empty message

        conv_dict = self.first_msg_dict
        if body in conv_dict:
            # This message has already been seen
            if len(self.conversations[self.conv_idx]) > conv_dict[body]['len']:
                # This conversation is longer, keep it and discard the other
                del self.conversations[conv_dict[body]['id']]
                conv_dict[body] = {'id': self.conv_idx, 'len': len(self.conversations[self.conv_idx])}
            else:
                # The other conversation is longer, keep that one
                if self.conv_idx in self.conversations:
                    self.conversations.pop(self.conv_idx)
                return False
        else:
            # The first message of this conversation has never been seen
            conv_dict[body] = {'id': self.conv_idx, 'len': len(self.conversations[self.conv_idx])}
        
        self.conversations[self.conv_idx].insert(0, {
            'body': scrubber.clean(body.strip()) if body else None,
            'header': scrubber.clean(subject.strip()) if subject else None,
            'date': date,
            'from': _from,
            'to': to,
            'folder_path': folder_path})
        
        return True
        
    def get_loaded_date_range(self) -> Optional[Tuple[int,int]]:
        """
        If a previous email csv was loaded, returns a tuple of the minimum
        and maximum date that was loaded
        """
        return self.prev_loaded_dates
    
    def read_from_file(self, filepath: str):
        """
        Reads messages from a previously saved csv file
        Useful for continuing an incomplete email dump
        """
        df = pd.read_csv(filepath)

        df['date'] = df[~df['date'].isna()]['date'].apply(lambda x: datetime.strptime(x, DATE_FORMAT))

        for row in df.itertuples():
            if row.conversation >= len(self.conversations):
                self.conversations.append([])

            self.conversations[row.conversation].append({
                'body': row.body,
                'header': row.header,
                'date': row.date,
                'from': row._7,
                'to': row.to,
                'folder_path': row.folder_path
            })

        dates = df[(~df['date'].isna()) & (df['turn'].isin([0]))]['date']
        min_date = min(dates)
        max_date = max(dates)
        self.prev_loaded_dates = (min_date,max_date)

    def save_to_file(self, filepath: str):
        """
        Saves the conversations to a csv
        """
        df_list = []

        print("Saving to csv...")
        for (conversation_id,conversation) in tqdm(self.conversations.items()):
            turn_idx = 0
            for message in conversation:
                date = message['date'].strftime(DATE_FORMAT) if message['date'] else None
                df_list.append({
                    'conversation': conversation_id,
                    'turn': turn_idx,
                    'body': message['body'],
                    'header': message['header'],
                    'date': date,
                    'from': int(message['from']),
                    'to': int(message['to']),
                    'folder_path': message['folder_path']})
                turn_idx += 1
        
        df = pd.DataFrame.from_dict(df_list)
        def writer():
            df.to_csv(filepath,encoding=ENCODING)

        write_file(writer)
        print(f"Finished, saved {len(df_list)} emails to csv.")
        
    def remove_duplicate_conversations(self):
        """
        Removes duplicate conversations from the message archive
        
        Since one conversation is created for every sent email, there may be duplicates if advisors
        send more one one message in the chain.
        If any pair of conversations has the first initial message, the shorter conversation chain
        will be discarded.
        """
        ids_to_discard = []
        conv_dict = {}
        
        print(f"Removing duplicate conversations")
        for id, conversation in enumerate(self.conversations):
            first_msg = conversation[0]['body']
            
            if first_msg in conv_dict:
                # The first message of this conversation has already been seen
                if len(conversation) > conv_dict[first_msg]['len']:
                    # This conversation is longer, keep it and discard the other
                    ids_to_discard.append(conv_dict[first_msg]['id'])
                    conv_dict[first_msg] = {'id': id, 'len': len(conversation)}
                else:
                    # The other conversation is longer, keep this one
                    ids_to_discard.append(id)
            else:
                # The first message of this conversation has never been seen
                conv_dict[first_msg] = {'id': id, 'len': len(conversation)}
                
        self.conversations = [j for i,j in enumerate(self.conversations) if i not in ids_to_discard]
            
        print(f"Removed {len(ids_to_discard)} duplicate conversations")
            

def get_email_type(email_line: str) -> EmailAddress:
    """
    Classifies an email address as one of the EmailAddress types
    """
    if not email_line: return EmailAddress.NONE
    elif ADVISING_NAME in email_line or ADVISING_ADDRESS in email_line:
        return EmailAddress.ADVISING
    elif re.search(internal_address_regex, email_line): return EmailAddress.INTERNAL
    else: return EmailAddress.STUDENT

def get_recipient_address(message):
    """
    Given an Outlook COM message, find the email address of the recipient
    """
    if message.Recipients.Count == 0: return ''
    recipient = message.Recipients[0].AddressEntry

    if recipient.Type=='EX':
        if recipient.GetExchangeUser() != None:
            return recipient.GetExchangeUser().PrimarySmtpAddress
        elif dist_list := recipient.GetExchangeDistributionList():
            return dist_list.PrimarySmtpAddress
        else:
            return ''
    else:
        return recipient.Address
    
def create_domain_set(message_list):
    """
    Create a list of all email domains that are sent to
    Use this to identify 'internal' addresses
    """
    current_message = message_list.GetFirst()
    domain_set = set()
    
    with tqdm(total=message_list.Count) as pbar:
        while current_message:
            address = get_recipient_address(current_message)
            domains = re.findall("(?<=@)[^\s]*\.[^\s]*", address)
            domain_set.update(domains)
            pbar.update(1)
            current_message = message_list.GetNext()
            
    for domain in domain_set:
        print(domain)

def handle_sent_message(message: Any, messages: Messages):
    """
    Add the relevant information for an Outlook COM message to the repository
    Creates separate messages in the same conversation for any replies in this message body
    """
    if message.Class != MAIL_ITEM_CLASS: return # skip a non-mail item

    # Split the email into replies
    messages.new_conversation()
    parsed_email = EmailReplyParser(languages=['en']).read(message.Body)

    # Add the most recent message
    recipient_addr = get_recipient_address(message)
    add_msg_result = messages.add_message(message.SentOn, EmailAddress.ADVISING, 
                         get_email_type(recipient_addr), message.Subject, parsed_email.replies[0].body, 'Sent Items')
    
    if not add_msg_result:
        # This is a duplicate converation, we can skip replies
        return
    
    # Add the replies
    for reply in parsed_email.replies[1:]:
        if reply.headers == '': continue
        try:
            # Check if there are any quotes to remove from the text
            body = ""
            quote_unwrapped = quotequail.unwrap(reply.body)
            if quote_unwrapped and quote_unwrapped["type"] == "quote":
                if "text_top" in quote_unwrapped:
                    body = quote_unwrapped["text_top"]
                if "text_bottom" in quote_unwrapped:
                    body += "\n"
                    body += quote_unwrapped["text_bottom"]
            else:
                body = reply.body
            
            # Attempt to extract information from headers
            reply.headers = reply.headers.encode('ascii', 'ignore').decode('ascii') # remove unicode characters
            
            if 'wrote:' in reply.headers:
                (date_text, date) = dateparser.search.search_dates(reply.headers, settings={'RETURN_AS_TIMEZONE_AWARE': True})[0]
                from_text = re.search(f'(?<={re.escape(date_text)})(.|\n)*(?=wrote:)',reply.headers).group()
                add_msg_result = messages.add_message(date, get_email_type(from_text), get_email_type(None), '', body, 'Sent Items')
            else:
                from_line = to_line = date = subject = None
                if match := re.search('From:?.*',reply.headers): from_line = match.group()
                if match := re.search('(To|Cc):?.*',reply.headers): to_line = match.group()
                if match := re.search('((?<=Sent: )|(?<=Sent )|(?<=Date: )|(?<=Date )).*',reply.headers):
                    date = dateparser.parse(match.group(), settings={'RETURN_AS_TIMEZONE_AWARE': True})
                elif dates := dateparser.search.search_dates(reply.headers, settings={'RETURN_AS_TIMEZONE_AWARE': True}):
                    (_, date) = dates[0]
                if match := re.search('((?<=Subject: )|(?<=Subject ))(.|\n)*',reply.headers): subject = match.group()
                add_msg_result = messages.add_message(date, get_email_type(from_line), get_email_type(to_line), subject, body, 'Sent Items')
            if not add_msg_result:
                # This is a duplicate converation, we can skip replies
                return
        except:
            print(f'Could not parse email reply headers for "{message.Subject}"')

def parse_emails(output_path: str, outlook_folder: Any, messages: Messages):
    """
    For every email in the given outlook folder, add all messages to the Messages repository
    Will split out replies in all messages, so best to use just the sent folder.
    """
    message_list = outlook_folder.Items
    message_list.Sort('[SentOn]',True)

    if dates := messages.get_loaded_date_range():
        filter = f"[SentOn] < '{dates[0].strftime(FILTER_DATE_FORMAT)}' Or [SentOn] > '{dates[1].strftime(FILTER_DATE_FORMAT)}'"
        message_list = message_list.Restrict(filter) 

    current_message = message_list.GetFirst()
    counter = 0
    with tqdm(total=message_list.Count) as pbar:
        while current_message:
            handle_sent_message(current_message, messages)
            current_message = message_list.GetNext()
            pbar.update(1)
            counter += 1
            if counter % SAVE_INTERVAL == 0:
                messages.save_to_file(output_path) # periodically save progress

def get_emails(output_path, advising_inbox_name=ADVISING_INBOX_NAME, send_folder='Sent Items'):
    """
    Gets and cleans all emails from the sent folder
    """
    outlook = client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    messages = Messages()

    if os.path.exists(output_path):
        print(f"The file {output_path} already exists")
        response = input(f"Do you want to overwrite it (o), or continue an incomplete email dump (c)? (q to quit) <o/c> ")
        if response.lower() == 'o':
            pass
        elif response.lower() == 'c':
            messages.read_from_file(output_path)
        else: return

    print("Getting messages..")
    folder = None
    try:
        folder = outlook.Folders[advising_inbox_name].Folders[send_folder]
    except:
        print(f"Couldn't find the folder named {send_folder}, cancelling operation")
        return

    print(f"Getting messages from folder {send_folder}")
    parse_emails(output_path,folder,messages)
    
    # print(f"Removing duplicate conversations")
    # messages.remove_duplicate_conversations()

    messages.save_to_file(output_path)

def read_internal_domains(filename):
    """
    Reads the list of domain names to treat as internal recipients
    """
    global ubc_internal_addresses, internal_address_regex
    
    with open(filename) as file:
        ubc_internal_addresses = ['@' + line.rstrip() for line in file]
    
    internal_address_regex = re.compile(f'.*({"|".join(ubc_internal_addresses)})')
        
def main():
    read_internal_domains(get_filepath(config, 'download_emails', 'INTERNAL_DOMAINS_FILE'))
    get_emails(get_filepath(config, 'download_emails', 'OUT_FILE'))

if __name__ == '__main__':
    main()