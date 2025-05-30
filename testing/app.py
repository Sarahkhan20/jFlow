# from flask import Flask, request, jsonify
import pandas as pd
from Models import get_HF_embeddings, cosine
import os
from dotenv import load_dotenv
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import string
import re

# Download required NLTK data
nltk.download('stopwords')
nltk.download('punkt')
nltk.download('punkt_tab')
import json

load_dotenv()

import google.generativeai as genai
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
from chains import Chain
chain = Chain()

# app = Flask(__name__)

def get_gemini_response(input):
    model = genai.GenerativeModel("gemini-pro")
    response = model.generate_content(input)
    return response.text

def get_key_info(text):
  """
  Extracts key information from the resume using Gemini
  """
  key_info_prompt = """
  This is a resume for a job applicant. Please analyze the text and provide the following information in a clear and concise format:

  * Name
  * Contact Information (Phone, Email, LinkedIn, Github, etc)
  * Education (Degree, Year, Institution, marks)
  * Work Experience/Internships (Company, Dates, Description)
  * Skills
  * Relevant Coursework

  Resume: {text}
  """
  response = get_gemini_response(key_info_prompt.format(text='\n'.join(text)))
  return response

# System Template
sys_prompt = """
You are an advanced Applicant Tracking System (ATS) with extensive experience in the tech industry, particularly in software engineering. Your primary function is to rigorously evaluate resumes against provided job descriptions. Consider the following guidelines:

1. Approach: Be highly critical and detail-oriented. The job market is extremely competitive, and only the most qualified candidates should receive high ratings.

2. Matching Criteria:
- Essential Skills: Penalize heavily for missing must-have technical skills.
- Experience: Scrutinize the depth and relevance of work experience.
- Education: Consider the relevance and prestige of educational background.
- Projects: Evaluate the complexity and relevance of listed projects.
- Achievements: Look for quantifiable impacts and innovations.

3. Keyword Analysis:
- Identify all keywords in the job description.
- Check for exact matches and semantically similar terms in the resume.
- Penalize for missing important keywords or concepts.

4. Scoring:
- Start from 0% match and add points for meeting criteria.
- Deduct points for missing essential elements.
- Be very selective with high scores (>80% should be rare).

5. Feedback:
- Provide a brief, critical analysis of the resume's strengths and weaknesses.
- List missing keywords and suggest improvements.
- Explain your scoring rationale.

6. Format your response as follows:
{{"JD Match": "X%",
    "Analysis": "Your critical analysis here",
    "Missing Keywords": ["keyword1", "keyword2", ...],
    "Improvement Suggestions": ["suggestion1", "suggestion2", ...]
}}

Remember, your goal is to identify only the most qualified candidates. Be thorough, critical, and maintain high standards in your evaluation.

Resume: {text}
Job Description: {JD}
"""

def preprocess_text(text):
    """Clean and preprocess text for BERT"""
    # Convert to string and lowercase
    text = str(text).lower()
    
    # Remove special characters and numbers
    text = re.sub(r'[^a-zA-Z\s]', '', text)
    
    # Tokenize
    tokens = word_tokenize(text)
    
    # Remove stopwords
    stop_words = set(stopwords.words('english'))
    tokens = [t for t in tokens if t not in stop_words]
    
    # Remove punctuation
    tokens = [t for t in tokens if t not in string.punctuation]
    
    # Rejoin text
    return ' '.join(tokens)

# @app.route('/predictMatch', methods=['POST'])
def predict_match(resume, jd):
    # data = request.json
    # resume = data.get('resume')
    # jd = data.get('jd')

    if not resume or not jd:
        return {"error": "Resume and Job Description are required!"}

    # Llama 3.1 Prediction
    llama_match = chain.resume_jd_match(resume, jd)

    # Gemini Prediction
    gemini_match = get_gemini_response({"resume": resume, "jd": jd})

    # HuggingFace BERT Prediction
    resume_embeddings = get_HF_embeddings([get_HF_embeddings(resume_text) for resume_text in resume])
    jd_embeddings = get_HF_embeddings([jd])
    bert_match = cosine(resume_embeddings, jd_embeddings)[0]

    return {
        "llama_3.1_match": llama_match,
        "gemini_match": gemini_match,
        "bert_match": bert_match
    }

# @app.route('/processCSV', methods=['POST'])
def process_csv(csv_url):
    # Check if csv_url is provided
    if not csv_url:
        return {"error": "CSV URL is required!"}

    try:
        # Read the CSV file
        df = pd.read_csv(csv_url)

        # Check if the required columns are present
        if 'resume_content' not in df.columns or 'jd_content' not in df.columns:
            return {"error": "CSV must contain 'resume_content' and 'jd_content' columns!"}

        results = []
        batch_size = 10
        total_rows = len(df)

        for i in range(0, total_rows, batch_size):
            # Process each batch
            batch_df = df.iloc[i:i + batch_size]
            batch_results = []
            for _, row in batch_df.iterrows():
                try:
                    resume = row['resume_content']
                    jd = row['jd_content']

                    # LLAMA Processing
                    resume_info = chain.extract_resume_details(resume)
                    job_info = chain.extract_jobs(jd)
                    llama_response = chain.resume_jd_match(resume_info, job_info)
                    llama_match = llama_response['match_percentage'].replace("%", "")

                    # GEMINI Processing
                    gemini_match = "0"
                    try:
                        resume_key_info = get_key_info(resume)
                        gemini_response = get_gemini_response(sys_prompt.format(text='\n'.join(resume_key_info), JD=jd))
                        gemini_response = json.loads(gemini_response)
                        gemini_match = gemini_response['JD Match'].replace("%", "")  # Extract numerical match
                    except Exception as e:
                        print("Error in Gemini:", str(e))

                    clean_resume = preprocess_text(resume)
                    clean_jd = preprocess_text(jd)

                    # BERT Processing
                    resume_embeddings = [get_HF_embeddings(clean_resume)]
                    jd_embeddings = get_HF_embeddings(clean_jd)
                    bert_match = cosine(resume_embeddings, jd_embeddings)[0]

                    batch_results.append({
                        "llama_3.1_match": llama_match,
                        "gemini_match": gemini_match,
                        "bert_match": bert_match
                    })
                except Exception as e:
                    print("Error:", str(e))
                    batch_results.append({
                        "llama_3.1_match": "0",
                        "gemini_match": "0",
                        "bert_match": "0"
                    })
                
                print(f"ROW : {i+1}")
            # Add the batch results back to the batch DataFrame
            batch_df.loc[:, 'llama_3.1_match'] = [result['llama_3.1_match'] for result in batch_results]
            batch_df.loc[:, 'gemini_match'] = [result['gemini_match'] for result in batch_results]
            batch_df.loc[:, 'bert_match'] = [result['bert_match'] for result in batch_results]

            # Save the batch to CSV after processing
            output_path = os.path.join(f"results/processed_results_{i // batch_size + 1}.csv")
            batch_df.to_csv(output_path, index=False)

            print(f"Processed Batch {i // batch_size + 1}")

        return {"message": "CSV processed successfully!"}

    except Exception as e:
        return {"error": str(e)}

# if __name__ == '__main__':
#     app.run(debug=True)
ress = process_csv("filtered_testcases.csv")
print(ress)