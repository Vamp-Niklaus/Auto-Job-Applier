'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit

GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

------------------------------------------------------------------------------
Provider-agnostic AI layer built on LangChain + LangGraph.

A single code path serves OpenAI, any OpenAI-compatible endpoint (Ollama,
LM Studio, DeepSeek, vLLM, and similar) and Google Gemini. Pick the provider,
model, key and URL in `config/secrets.py`.

Public interface (used by runAiBot.py):
    create_ai_client()  -> AIClient | None
    extract_skills(client, job_description) -> dict
    answer_question(client, question, ...)  -> str
    close_ai_client(client) -> None
------------------------------------------------------------------------------
'''

from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END

import config.secrets as cfg
from config.settings import showAiErrorAlerts
from modules.helpers import print_lg, critical_error_log, convert_to_json
from modules.ai.prompts import extract_skills_prompt, ai_answer_prompt, job_score_prompt

confirm = None


# Whether to keep popping up AI error dialogs (disabled once the user asks to pause them).
_alerts_enabled = bool(showAiErrorAlerts)


def _ai_error_alert(message: str, error: Exception, title: str = "AI Error") -> None:
    '''Log an AI error and (optionally) show a dismissible dialog, mirroring the rest of the tool.'''
    global _alerts_enabled
    if _alerts_enabled and confirm is not None:
        try:
            choice = confirm(f"{message}\n\n{error}\n", title, ["Pause AI alerts", "Okay, continue"])
            if choice == "Pause AI alerts":
                _alerts_enabled = False
        except Exception:
            pass
    critical_error_log(message, error)


def _resolve_provider(name: Optional[str]) -> str:
    '''
    Map the user-facing provider name to a LangChain model provider.
    Everything OpenAI-compatible (OpenAI, Ollama, LM Studio, DeepSeek, vLLM, ...)
    runs through the "openai" provider by pointing the URL at the right server.
    '''
    n = (name or "openai").strip().lower()
    if n in ("gemini", "google", "google_genai", "google-genai"):
        return "google_genai"
    return "openai"


def _msg_text(message) -> str:
    '''Extract plain text from a LangChain message (handles str content and content-block lists).'''
    text = getattr(message, "text", None)
    if callable(text):
        try:
            text = text()
        except Exception:
            text = None
    if isinstance(text, str) and text:
        return text
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text") or block.get("content") or "")
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


class AIClient:
    '''Small holder for the chat model and its compiled answer graph.'''
    def __init__(self, model, config_id=None, provider=None, model_name=None):
        self.model = model
        self.config_id = config_id
        self.provider = provider
        self.model_name = model_name
        self.answer_graph = _build_answer_graph(model)


class RoundRobinAIClient:
    def __init__(self, clients: list[AIClient]):
        self.clients = clients
        self.index = 0
        self.failures = {} # config_id -> failure count

    def get_next(self) -> Optional[AIClient]:
        if not self.clients:
            return None
        client = self.clients[self.index]
        self.index = (self.index + 1) % len(self.clients)
        return client

    def report_failure(self, client: AIClient) -> None:
        if not client or client.config_id == "legacy":
            return
        cid = client.config_id
        self.failures[cid] = self.failures.get(cid, 0) + 1
        print_lg(f"⚠️ API Key failed: {client.provider} | {client.model_name} (Failures: {self.failures[cid]}/2)")
        if self.failures[cid] >= 2:
            print_lg(f"❌ Removing non-functional AI API key from round-robin pool: {client.provider} | {client.model_name}")
            # Remove from active clients list
            self.clients = [c for c in self.clients if c.config_id != cid]
            # Reset index bounds
            if self.clients:
                self.index = self.index % len(self.clients)
            
            # De-verify in user_config.json
            try:
                from config._overrides import USER_CONFIG_PATH
                if os.path.exists(USER_CONFIG_PATH):
                    with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                    if "secrets" in config_data and "ai_apis" in config_data["secrets"]:
                        for api in config_data["secrets"]["ai_apis"]:
                            if api.get("id") == cid:
                                api["verified"] = False
                                break
                        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
                            json.dump(config_data, f, indent=2, ensure_ascii=False)
            except Exception as conf_err:
                print_lg("Failed to auto-update user_config.json on API key de-verification:", conf_err)
            
            if not self.clients:
                raise Exception("LLM stopped working. All keys are unverified.")


def create_ai_client() -> Optional[RoundRobinAIClient]:
    '''
    Build list of chat models from `config/secrets.py` ai_apis.
    Falls back to legacy config if no verified APIs exist in the list.
    '''
    if not cfg.use_AI:
        print_lg("AI is turned off (use_AI = False in config/secrets.py). Skipping AI setup.")
        return None
    try:
        verified_apis = [api for api in getattr(cfg, "ai_apis", []) if api.get("verified") and api.get("enabled") != False]
        clients = []

        for api in verified_apis:
            try:
                provider = _resolve_provider(api.get("provider"))
                model_name = api.get("model", "")
                api_key = api.get("api_key", "").strip()
                api_url = api.get("api_url", "").strip()
                temperature = getattr(cfg, "llm_temperature", None)

                kwargs = {"timeout": 30.0}
                if temperature is not None:
                    kwargs["temperature"] = temperature

                if provider == "google_genai":
                    if api_key and api_key.lower() != "not-needed":
                        os.environ["GOOGLE_API_KEY"] = api_key
                    model = init_chat_model(model_name, model_provider="google_genai", **kwargs)
                else:
                    kwargs["api_key"] = api_key or "not-needed"
                    if api_url:
                        kwargs["base_url"] = api_url
                    model = init_chat_model(model_name, model_provider="openai", **kwargs)
                
                clients.append(AIClient(model, config_id=api.get("id"), provider=api.get("provider"), model_name=model_name))
                print_lg(f"Loaded verified AI API: {api.get('provider')} | {model_name}")
            except Exception as api_err:
                print_lg(f"Failed to load verified AI API {api.get('provider')} | {api.get('model')}:", api_err)

        # Fallback to legacy single key if no custom verified list is present
        if not clients:
            try:
                # Read legacy parameters if defined in secrets.py
                legacy_provider = getattr(cfg, "ai_provider", "openai")
                legacy_model = getattr(cfg, "llm_model", "gpt-4o-mini")
                legacy_key = getattr(cfg, "llm_api_key", "not-needed")
                legacy_url = getattr(cfg, "llm_api_url", "")
                
                provider = _resolve_provider(legacy_provider)
                temperature = getattr(cfg, "llm_temperature", None)

                kwargs = {"timeout": 30.0}
                if temperature is not None:
                    kwargs["temperature"] = temperature

                if provider == "google_genai":
                    if legacy_key and legacy_key.lower() != "not-needed":
                        os.environ.setdefault("GOOGLE_API_KEY", legacy_key)
                    model = init_chat_model(legacy_model, model_provider="google_genai", **kwargs)
                else:
                    kwargs["api_key"] = legacy_key or "not-needed"
                    if legacy_url:
                        kwargs["base_url"] = legacy_url
                    model = init_chat_model(legacy_model, model_provider="openai", **kwargs)
                clients.append(AIClient(model, config_id="legacy", provider=legacy_provider, model_name=legacy_model))
                print_lg(f"Loaded fallback AI API: {legacy_provider} | {legacy_model}")
            except Exception as e:
                print_lg("Could not build fallback AI client:", e)

        if not clients:
            _ai_error_alert("No verified AI APIs found, and fallback legacy configuration failed.", Exception("No AI clients could be created."))
            return None

        print_lg(f"---- AI MULTI-CLIENT READY (Total: {len(clients)}) ----")
        return RoundRobinAIClient(clients)
    except Exception as e:
        _ai_error_alert("Failed to initialize AI Client pool.", e)
        return None


def close_ai_client(client: Optional[AIClient]) -> None:
    '''LangChain chat models hold no long-lived connection to close; kept for interface symmetry.'''
    return None


# --------------------------------------------------------------------------- #
# Skill extraction (structured output)
# --------------------------------------------------------------------------- #
class ExtractedSkills(BaseModel):
    '''Skills extracted from a job description and grouped into five buckets.'''
    tech_stack: list[str] = Field(default_factory=list, description="Programming languages, frameworks, libraries, databases and tools")
    technical_skills: list[str] = Field(default_factory=list, description="Technical expertise beyond specific tools (system design, data engineering, ...)")
    other_skills: list[str] = Field(default_factory=list, description="Non-technical / soft skills (communication, leadership, teamwork, ...)")
    required_skills: list[str] = Field(default_factory=list, description="Skills explicitly listed as required or expected")
    nice_to_have: list[str] = Field(default_factory=list, description="Skills listed as preferred or beneficial but not mandatory")


def extract_skills(client: Optional[RoundRobinAIClient], job_description: str, stream: bool = False) -> dict:
    '''
    Extract and classify skills from a job description.
    Returns a dict with the five skill buckets, or an ``{"error": ...}`` dict on failure.
    '''
    if not client or not job_description:
        return {"error": "AI client unavailable or empty job description."}
    
    attempts = len(client.clients) if hasattr(client, "clients") else 1
    last_err = None

    for _ in range(attempts):
        active_client = client.get_next() if hasattr(client, "get_next") else client
        if not active_client:
            return {"error": "No active AI client in the pool."}

        prompt = extract_skills_prompt.format(job_description)
        try:
            structured = active_client.model.with_structured_output(ExtractedSkills)
            result = structured.invoke(prompt)
            print_lg(f"=== LLM CALL [API: {active_client.provider} | {active_client.model_name}] (extract_skills) ===\n{prompt}\n=== RESPONSE ===\n{result.model_dump()}\n================================")
            return result.model_dump()
        except Exception as e:
            # Some local or older models don't support structured output — fall back to plain JSON parsing.
            print_lg(f"Structured skill extraction failed for {active_client.provider} | {active_client.model_name}, trying plain parsing...", e)
            try:
                raw_res = convert_to_json(_msg_text(active_client.model.invoke(prompt)))
                if "error" not in raw_res:
                    return raw_res
            except Exception:
                pass
            
            if hasattr(client, "report_failure"):
                client.report_failure(active_client)
            last_err = e

    _ai_error_alert("All verified AI APIs in the pool failed to extract skills.", last_err)
    return {"error": f"All AI client configurations in the pool failed: {last_err}"}


# --------------------------------------------------------------------------- #
# Question answering (LangGraph pipeline)
# --------------------------------------------------------------------------- #
class _AnswerState(TypedDict, total=False):
    question: str
    options: Optional[list]
    question_type: str
    job_description: Optional[str]
    about_company: Optional[str]
    user_information: Optional[str]
    prompt: str
    raw: str
    answer: str


def _build_answer_graph(model):
    '''
    Compile a small LangGraph pipeline for answering a form question:

        build_prompt -> generate -> (route by question type) -> format_text | select_option

    Free-text questions are returned as-is; select questions are snapped to one of
    the allowed options. The graph gives us a clean seam to extend later (validation,
    retries, resume/cover-letter nodes).
    '''
    def build_prompt(state: _AnswerState) -> dict:
        prompt = ai_answer_prompt.format(state.get("user_information") or "N/A", state.get("question") or "")
        jd = state.get("job_description")
        if jd and jd != "Unknown":
            prompt += f"\n\nJob description:\n{jd}"
        about = state.get("about_company")
        if about and about != "Unknown":
            prompt += f"\n\nAbout the company:\n{about}"
        options = state.get("options")
        if options:
            prompt += "\n\nAnswer with exactly one of these options:\n" + "\n".join(f"- {o}" for o in options)
        return {"prompt": prompt}

    def generate(state: _AnswerState) -> dict:
        message = model.invoke(state["prompt"])
        raw = _msg_text(message).strip()
        print_lg(f"=== LLM CALL (answer_question) ===\n{state['prompt']}\n=== RESPONSE ===\n{raw}\n==================================")
        return {"raw": raw}

    def format_text(state: _AnswerState) -> dict:
        return {"answer": (state.get("raw") or "").strip()}

    def select_option(state: _AnswerState) -> dict:
        raw = (state.get("raw") or "").strip()
        options = state.get("options") or []
        for opt in options:                       # exact
            if raw == opt:
                return {"answer": opt}
        low = raw.lower()
        for opt in options:                       # case-insensitive
            if low == opt.lower():
                return {"answer": opt}
        for opt in options:                       # substring (either direction)
            if opt.lower() in low or low in opt.lower():
                return {"answer": opt}
        return {"answer": raw}

    def route(state: _AnswerState) -> str:
        return "select" if state.get("question_type") in ("single_select", "multiple_select") else "text"

    graph = StateGraph(_AnswerState)
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("generate", generate)
    graph.add_node("format_text", format_text)
    graph.add_node("select_option", select_option)
    graph.add_edge(START, "build_prompt")
    graph.add_edge("build_prompt", "generate")
    graph.add_conditional_edges("generate", route, {"text": "format_text", "select": "select_option"})
    graph.add_edge("format_text", END)
    graph.add_edge("select_option", END)
    return graph.compile()


def answer_question(
    client: Optional[RoundRobinAIClient],
    question: str,
    options: Optional[list] = None,
    question_type: str = "text",
    job_description: Optional[str] = None,
    about_company: Optional[str] = None,
    user_information_all: Optional[str] = None,
    stream: bool = False,
) -> str:
    '''
    Generate an answer to a single application-form question.
    Returns the answer string, or "" if AI is unavailable or the call fails.
    '''
    if not client or not question:
        return ""
    
    attempts = len(client.clients) if hasattr(client, "clients") else 1
    last_err = None

    for _ in range(attempts):
        active_client = client.get_next() if hasattr(client, "get_next") else client
        if not active_client:
            return ""

        try:
            final = active_client.answer_graph.invoke({
                "question": question,
                "options": options,
                "question_type": question_type,
                "job_description": job_description,
                "about_company": about_company,
                "user_information": user_information_all,
            })
            answer = final.get("answer", "") or ""
            print_lg(f'AI [API: {active_client.provider} | {active_client.model_name}] answered "{question}" -> "{answer}"')
            return answer
        except Exception as e:
            print_lg(f"AI answer failed for {active_client.provider} | {active_client.model_name}, trying next provider...", e)
            if hasattr(client, "report_failure"):
                client.report_failure(active_client)
            last_err = e

    _ai_error_alert("All verified AI APIs in the pool failed to answer the question.", last_err)
    return ""


# --------------------------------------------------------------------------- #
# Job relevance scoring
# --------------------------------------------------------------------------- #
def score_job(
    client: Optional[RoundRobinAIClient],
    job_description: str,
    resume_text: str,
    candidate_years: float,
    score_threshold: int = 50,
) -> tuple[int, str]:
    '''
    Score how well the candidate fits a job posting (0-100).

    HARD RULE: If the job description mentions required experience > candidate_years + 2,
    we return score 0 immediately WITHOUT calling the LLM, to save API quota.

    Returns (score, reason) tuple.
    '''
    # --- LLM scoring ---
    if not client or not resume_text or not job_description:
        return -1, "Scoring skipped (AI off or no resume text)."  # -1 = don't filter

    attempts = len(client.clients) if hasattr(client, "clients") else 1
    last_err = None

    for _ in range(attempts):
        active_client = client.get_next() if hasattr(client, "get_next") else client
        if not active_client:
            return -1, "No active AI client in pool."

        prompt = job_score_prompt.replace("{{resume}}", resume_text).replace("{{job}}", job_description).replace("{{candidate_years}}", str(candidate_years)).replace("{{cutoff_years}}", str(candidate_years + 2))
        try:
            raw = _msg_text(active_client.model.invoke(prompt)).strip()
            print_lg(f"=== LLM CALL [API: {active_client.provider} | {active_client.model_name}] (score_job) ===\n{prompt[:400]}...\n=== RESPONSE ===\n{raw}\n===========================")
            data = convert_to_json(raw)
            score = int(data.get("score", -1))
            reason = str(data.get("reason", ""))
            label = "✅ APPLY" if score >= score_threshold else "⏭ SKIP"
            print_lg(f"[SCORE {score:3d}/100] {label} — {reason}")
            return score, reason
        except Exception as e:
            print_lg(f"Job scoring failed for {active_client.provider} | {active_client.model_name}, trying next provider...", e)
            if hasattr(client, "report_failure"):
                client.report_failure(active_client)
            last_err = e

    print_lg("All verified AI APIs in the pool failed to score the job.", last_err)
    # Raise exception to prevent blind applying (per user request: "I don't want to skip the LLM score.")
    raise Exception(f"All AI client configurations in the pool failed to score the job: {last_err}")
