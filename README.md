# Emails Processing

This is a collection of email processing scripts for evaluating student advising emails. The processing is split into several steps, detailed below. Configuration options can be specified in the ```config.ini``` file, which defined options for each step. Each step has a corresponding script in the ```scripts``` folder which can be run to perform the step. Data inputs/outputs for each step will be put in the ```data``` folder. For privacy reasons, the data is not included.

## Step 1: Download Emails

This step retrieves all emails from an Outlook mailbox on the same device, cleans them of personal information, and saves the results to a .csv file. This requires that you have all emails for the corresponding mailbox [downloaded from the server](https://www.thewindowsclub.com/make-outlook-download-all-emails-from-server). Specify the name of the mailbox with the ADVISING_INBOX_NAME option.

During the processing, all emails are passed through a [Scrubadub](https://scrubadub.readthedocs.io/en/stable/index.html) cleaner to remove any personal information. This includes email addresses, student ids, phone numbers, names, etc. The name detector uses a RoBERTa model through Scrubadub's Spacy extension, so it does take a considerable amount of time to download and scrub all emails. On a CPU-only device, it took ~13 hours to retrieve and clean ~50000 emails. The SAVE_INTERVAL config option, measured in number of messages, can be used to periodically save messages to a file in case of issues. When the script is run again, you can choose to continue from the previous save point. Note that the script scans the sent folder of the mailbox, which can result in duplicated conversations. Duplicated conversations are removed (prioritizing removal of the shorter conversation), so the number of messages saved to csv may be less than the SAVE_INTERVAL value.

Since email addresses are scrubbed from the data, we need to first determine the category of sender and receiver before the address is scrubbed. The categories are STUDENT, ADVISING, INTERNAL, or NONE. The ADVISING email address is identified by the configuration options ADVISING_NAME and ADVISING_ADDRESS. INTERNAL email addresses are those that should not be considered students, eg. University departments. The domain names that are considered INTERNAL are loaded from the text file specified by the INTERNAL_DOMAINS_FILE. All other email addresses are considered STUDENT, or NONE if blank.

## Step 2: Filter by Keyword (Optional)

This step is optional, and disabled by default in the config settings. If you choose to enable it, you can specify the HEADER_KW_FILE and BODY_KW_FILE options, which should be the name of a text file with a keyword/phrase per line. Any conversations containing the header or body keywords will be discarded. This step was developed but ultimately not used in our pipeline.

## Step 3: Extract Contents

At this point, the emails still contain a lot of irrelevant text such as greetings, signatures, or form data. Existing libraries to remove this information were not effective, so a transformer model was trained on 300 examples to extract only the relevant content from each email. You will likely need to train your own version of the model, adapted to the contents of your emails. 

---
### Training the extraction model

**Create the extraction training data**

1. I used [Label Studio](https://labelstud.io/guide/quick_start) as an annotation environment. I recommend installing label studio in a separate environment from where you installed the other email processing dependencies, to prevent dependency issues.
2. Create a new label studio project.
- Under "Data Import", drag and drop the csv file of emails (from step 2 if enabled, otherwise step 1). Select "Treat CSV/TSV as List of tasks".
- Under "Labeling Interface", select "custom" and input the following:
```
<View>
  <Header value="Select the relevant content of the email"/>
  <Text name="text" value="$body" granularity="word"/>
  
  <Labels name="question" toName="text">
    <Label value="Question" maxUsage="5" background="red"/>
  </Labels>
  
  <Labels name="answer" toName="text">
    <Label value="Answer" maxUsage="5" background="green"/>
  </Labels>
</View>
```
3. Once you save the project, you can start annotating samples. Select the "question" or "answer" label as appropriate, and drag over a section of the text to label it as the relevant content of the email. I annotated ~300 questions and answers each.
4. Once finished, export the annotated results as CSV. Rename the file to match the TRAINING_ANNOTATION_FILE value in the config.

**Training the extraction models**

1. For training, I would recommend running it as a Jupyter notebook in a cloud environment with a GPU instance, if you don't have a GPU locally. You will need to copy the files ```3_train_extractor.ipynb```, ```config.ini```, and TRAINING_ANNOTATION_FILE to your cloud environment. I used an AWS Sagemaker Studio g4dn.2xlarge instance.
2. Run through the steps of the notebook to train two models, one for question extraction and the other for answer extraction. You will need to provide a [HuggingFace Access Token](https://huggingface.co/docs/hub/security-tokens) with write access to the account where you want to save the model.
3. Once the models are trained, you can inspect their f1 scores and accuracy. You may find that you need to adjust the hyperparameters for better performance on your data. The models will be saved to HuggingFace under the names specified in the config HF_QUESTION_MODEL_NAME and HF_ANSWER_MODEL_NAME. You can also test the model's inference with the sample function included in at the bottom of ```3_train_extractor.ipynb```.
---

### Applying the extraction models
Once the extraction model is trained, it needs to be applied to the entire dataset. I also used an AWS SageMaker Studio notebook for this, with instance type ```g4dn.2xlarge```. The notebook ```3_extract_contents.ipynb``` will retrieve the trained model and apply it to the entire dataset, generating an output file with the name specified in the config.

## Step 4: Make Pairs
This step converts the list of individual emails into pairs of the form (student question, advisor answer). It also removes any conversations that are not initiated by students, and messages for which no content was extracted in step 3. The output file will organize the messages into "conversations" and "turns". A conversation is a thread of emails, which could contain multiple turns. Every turn begins with an email from a student as the question, and the advisor's next email is the answer.

## Step 5: Classify Emails (Optional)
This step will allow you to optionally train a supervised email classifier to recognize manually defined email classes. This may be useful if you only want to evaluate a certain category of messages. This step was developed but ultimately not used in our pipeline.

---
### Training the classifier model

**Create the classification training data**

1. Like in step 3, I used [Label Studio](https://labelstud.io/guide/quick_start) as an annotation environment.
- Under "Data Import", drag and drop the csv file of email pairs from step 4. Select "Treat CSV/TSV as List of tasks".
- Under "Labeling Interface", select "custom" and input the following, replacing/adding choice values with your own class names.
```
<View>
  <Header value="Question"/>
  
  <Text name="q" value="$question" saveTextResult="no"/>

  <Header value="Answer"/>
  <Text name="a" value="$answer" saveTextResult="no"/>
  
  <View style="box-shadow: 2px 2px 5px #999;                padding: 20px; margin-top: 2em;                border-radius: 5px;">
    <Header value="Answer class"/>
    <Choices name="a_class" toName="a" choice="single" showInLine="true">
      <Choice value="YOUR CLASS 1"/>
      <Choice value="YOUR CLASS 2"/>
      <Choice value="YOUR CLASS 3"/>
    </Choices>
  </View>
  
</View>
```
3. Once you save the project, you can start annotating samples. Select the appropriate class for each question/answer pair. I annotated ~300 pairs.
4. Once finished, export the annotated results as CSV. Rename the file to match the TRAINING_ANNOTATION_FILE value in the config.

**Training the classification model**

1. For training, I would recommend running it as a Jupyter notebook in a cloud environment with a GPU instance, if you don't have a GPU locally. You will need to copy the files ```5_train_classifier.ipynb```, ```config.ini```, and TRAINING_ANNOTATION_FILE to your cloud environment. I used an AWS Sagemaker Studio ```g4dn.xlarge``` instance.
2. Run through the steps of the notebook to train the classifier, similar to before.
3. Once the model is trained, you can inspect the scores and tune hyperparameters as necessary. The model will be saved to HuggingFace under the name specified in the config HF_CLASSIFIER_NAME. You can also test the model's inference with the sample function included in at the bottom of ```5_train_classifier.ipynb```.
---

### Applying the extraction model
Once the extraction model is trained, it needs to be applied to the entire dataset. I also used an AWS SageMaker Studio notebook for this, with instance type ```g4dn.xlarge```. You will need to copy the files ```5_classify_emails.ipynb```, ```config.ini```, and the output csv from step 4. The notebook ```5_classify_emails.ipynb``` will retrieve the trained model and apply it to the entire dataset, generating an output file with the name specified in the config. The output file will contain the new ```label``` column with the predicted labels for each sample. You could choose to filter your dataset on the label for future steps.

## Step 6: Cluster Emails
This step helps generate some insights into the contents of the emails dataset. With [BERTopic](https://maartengr.github.io/BERTopic/index.html), we can use unsupervised clustering algorithms to identify the most common types of questions.

I also recommend to run this in a cloud environment, since on the first run, you will need to generate embeddings with a GPU instance. Copy the files ```6_cluster_emails.ipynb```, ```config.ini```, and the output csv from step 4 to your cloud environment. I used an AWS Sagemaker Studio ```g4dn.xlarge``` instance for the first run, and ```ml.t3.medium``` for subsequent runs.

The notebook does a separate clustering for questions and answers. This is for two reasons: first, it allows more specialized clusters. Second, later we can evaluate the quality of our clusters by finding correlation between question and answer categories. If the clusters are meaningful, we should find high correlation.

BERTopic's clustering is not perfect, so some human intervention will be required. It has a feature to automatically reduce the number of topics, but I found it more effective to reduce to a still large number, and manually merge related topics. The notebook includes a sample of how to merge and manually rename the clusters. To make decisions about cluster contents, you can use the ```display_qs``` and ```display_as``` functions to display all questions/answers for a particular category, respectively.

Once the clustering is complete, there is a section to evaluate the resulting clusters. A correlation score between question and answer categories helps to identify the most common answer for different types of questions. We collect the most common URLs seen in each answer category, and the most "representative" samples per category according to BERTopic.


# Future Improvements

Several improvements could be made to improve this process:

- Hyperparameter tuning: There was minimal hyperparameter tuning for the first iteration of the process. Tuning could likely improve the performance of the transformer models and the clustering algorithms, though tuning the clustering algorithms is much more difficult. The correlation score might be useful as a metric.
- Information display: To better leverage the information, better graphical display / infographic might make it more accessible. 
- Merging / renaming interface: Addition of a more user-friendly interface to merge and rename categories would make the process easier and less time consuming.
- Incorporating LLMs: Incorporating an LLM could help with certain steps of the process, or to gather more information from the categories. A properly prompted LLM might be able to generate an FAQ or summary for each question/answer category.