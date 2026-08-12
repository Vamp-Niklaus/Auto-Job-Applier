# LinkedIn AI Auto Job Applier 🤖

A powerful open-source tool that automates job applications on LinkedIn. It runs locally on your computer, using your own LinkedIn account. It filters jobs by relevance, parses questions, tailors your resume/details using Generative AI models (LLMs), and applies automatically.

---

## ✨ Features

- **Automated Applying**: Cycles through job listings and handles form steps automatically.
- **AI-Powered Screening**: Pre-screens jobs using LLMs (e.g. Groq, Gemini) to score compatibility.
- **Dynamic Key Rotation**: Supports round-robin requests across multiple API keys.
- **Search Loop**: Cycles search terms and locations continuously.
- **Clean Dashboard**: A local web interface (Control Panel) to edit settings, manage API keys, and review history.
- **Application Logs**: Separate tab sections for successfully Applied and Skipped/Failed applications.

---

## ⚙️ Quick Start

### 1. Install Dependencies
Ensure you have **Python 3.10+** and **Google Chrome** installed.
Clone the repository and run:
```bash
pip install -r requirements.txt
```

### 2. Launch the Application
Start the local server by running:
```bash
# Windows
start.bat

# Linux / macOS
./start.sh
```

### 3. Configure & Run
1. Open the local address shown in the terminal (usually `http://127.0.0.1:5000`).
2. Go to the configuration tabs and enter your details (e.g., job titles, target location, experience, and Groq/Gemini API keys).
3. Under the **Run** tab, click **Start**. The scraper will spin up Chrome and begin applying.

---

## 📁 Repository Structure

- `app.py`: Flask web server hosting the Control Panel.
- `runAiBot.py`: Core Selenium scraper execution engine.
- `user_config.json`: Local profile configurations (never uploaded/committed).
- `config/`: Configuration scripts holding default overrides.
- `modules/`: Automation scripts, model handlers, and validation helpers.
- `templates/`: Control panel HTML front-end.

---

## 🐧 Socials

- **LinkedIn**: [Rakesh Kumar](https://www.linkedin.com/in/rakesh-d-kumar/)
- **GitHub**: [Vamp-Niklaus](https://github.com/Vamp-Niklaus)


