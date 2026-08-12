'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit

GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Prompt templates used by the AI layer (modules/ai/connections.py).
'''


##> Extract skills
# Used with `extract_skills_prompt.format(job_description)`.
extract_skills_prompt = """
You are a job requirements extractor and classifier. Your task is to extract all skills mentioned in a job description and classify them into five categories:
1. "tech_stack": Identify all skills related to programming languages, frameworks, libraries, databases, and other technologies used in software development. Examples include Python, React.js, Node.js, Elasticsearch, Algolia, MongoDB, Spring Boot, .NET, etc.
2. "technical_skills": Capture skills related to technical expertise beyond specific tools, such as architectural design or specialized fields within engineering. Examples include System Architecture, Data Engineering, System Design, Microservices, Distributed Systems, etc.
3. "other_skills": Include non-technical skills like interpersonal, leadership, and teamwork abilities. Examples include Communication skills, Managerial roles, Cross-team collaboration, etc.
4. "required_skills": All skills specifically listed as required or expected from an ideal candidate. Include both technical and non-technical skills.
5. "nice_to_have": Any skills or qualifications listed as preferred or beneficial for the role but not mandatory.

JOB DESCRIPTION:
{}
"""
#<


##> Answer a form question
# Used with `ai_answer_prompt.format(user_information, question)`.
ai_answer_prompt = """
You are helping a job seeker fill in a job-application form. Answer the single question below the way the applicant would, in the first person, using the applicant's information whenever it is relevant.

Formatting rules:
- If the question asks for a number, a count, or years/months of experience, reply with just the number (for example: 3).
- If it is a yes/no question, reply with exactly "Yes" or "No".
- If it asks for a short answer, reply in a single sentence.
- If it asks for a longer or free-text answer, reply with a natural, well-structured response of at most 350 characters.
- Never repeat the question, never add labels, never add commentary. Return only the answer itself.

Applicant information:
{}

Question:
{}
"""
#<


##> Job relevance scoring
# Used with `job_score_prompt.format(resume_text, job_description, candidate_years)`.
# HARD RULE: If experience_gap > 2 years, caller should return score 0 immediately without calling LLM.
job_score_prompt = """
You are a strict technical recruiter scoring a candidate's fit for a job.
The candidate has {{candidate_years}} years of experience.

Output ONLY valid JSON, no other text:
{{"score": <0-100>, "reason": "<one short sentence>"}}

HARD EXPERIENCE LIMIT (Check this first):
- If the job description requires strictly MORE than {{cutoff_years}} years of experience (required years > {{cutoff_years}}), you MUST return: {{"score": 0, "reason": "Experience gap too large: job needs N+ years, candidate has only {{candidate_years}} year(s)."}}
- Note: A requirement of exactly "{{cutoff_years}} years" or "{{cutoff_years}}+ years" is eligible for evaluation (e.g. required is 3+ years when candidate has 1 year means a gap of exactly 2, which is eligible). Only auto-skip as 0 if the required experience is 4+ years, 5+ years, or Senior/Lead/Staff roles.

Scoring for eligible cases (required experience <= {{cutoff_years}} years):
- Strong skills/tech stack match with slight under-experience: 55-75
- Good title match, minor gaps: 60-80
- Perfect match (skills + experience): 80-100
- Location or visa requirement mismatch: -20 pts

Candidate Resume:
{{resume}}

Job Posting:
{{job}}
"""
#<
