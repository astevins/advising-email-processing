from enum import IntEnum
import os

DATE_FORMAT = '%d-%m-%Y %I:%M:%S'
FILTER_DATE_FORMAT = '%#m/%#d/%y %#H:%M %p' if os.name == 'nt' else '%-m/%-d/%y %-H:%M %p'

# Represents an email address, either student or advisor
class EmailAddress(IntEnum):
    STUDENT = 1,
    ADVISING = 2,
    INTERNAL = 3,
    NONE = 4
    
# Utility functions
def write_file(writer):
    """
    Tries to write a file, and requests user input to try again on failure.
    """
    
    response = 'y'
    while(response == 'y'):
        try:
           writer()
           print("Complete")
           return
        except Exception as e:
            print(f"Unable to write to file: {str(e)}")
            print("Could not save the files. Make sure the files to write are not open.")
            response = input("Try saving files again? <y,n> ")
            
def get_filepath(config, config_step, name):
    """
    Gets a filepath from the config
    """
    return os.path.join(config["global"]["DATA_DIR"], config[config_step][name])
            