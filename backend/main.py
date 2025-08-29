from math import log
import os
import json
import logging
from click import prompt
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, ValidationError
from typing import List, Optional, final
from semantic_kernel import Kernel
from semantic_kernel.agents import AgentRegistry, ChatCompletionAgent, AzureResponsesAgent
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, AzureChatPromptExecutionSettings
from semantic_kernel.functions import KernelArguments
from dotenv import load_dotenv

load_dotenv()

# Logging configuration:
# Root logger -> INFO (so external libraries don't spam DEBUG)
# 'app' logger -> DEBUG (full verbosity for our application only)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("app")
logger.setLevel(logging.DEBUG)
logger.propagate = False  # prevent double logging via root
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.DEBUG)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_h)

logger.info("Environment variables loaded.")
logger.debug(f"AZURE_OPENAI_ENDPOINT={os.getenv('AZURE_OPENAI_ENDPOINT')}")
logger.debug(f"AZURE_OPENAI_CHAT_DEPLOYMENT_NAME={os.getenv('AZURE_OPENAI_CHAT_DEPLOYMENT_NAME')}")

AZURE_OPENAI_CHAT_DEPLOYMENT_NAME = os.getenv('AZURE_OPENAI_CHAT_DEPLOYMENT_NAME')
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
AZURE_OPENAI_API_KEY = os.getenv('AZURE_OPENAI_API_KEY')

# Define YAML agent specs
BLOG_POST_AGENT_YAML = '''
type: chat_completion_agent
name: BlogWriterAgent
description: An agent that generates blog posts about a given topic.
instructions: |
  Write a detailed blog post about {{$topic}}. The blog post should be approximately {{$length}} paragraphs long and cover key aspects of the topic.
  Your output format is markdown only. Adhere to the inputs provided by the user.
model:
  id: gpt-5-mini
  options:
    temperature: 0.9
inputs:
  topic:
    description: The topic of the blog post.
    required: true
  length:
    description: The number of paragraphs in the blog post.
    required: true
    default: 5
template:
  format: semantic-kernel
'''

SEO_AGENT_YAML = '''
type: chat_completion_agent
name: SEOOptimizerAgent
description: An agent that optimizes blog articles for SEO.
instructions: |
  Rewrite the following blog article to be SEO optimized. Use relevant keywords, improve readability, and ensure the content is engaging for search engines. Return a structured output containing:
    - title
    - meta description
    - slug
    - h1 and h2 headings
    - the revised article (keep length and format the same; only optimize for SEO)
    - a list of improvements
    - relevant SEO keywords
    - internal and external links
    - readability score
    - a call to action
  # Article
  {{$article}}
inputs:
  article:
    description: The original blog article to optimize.
    required: true
model:
  id: gpt-5-mini
  options:
    temperature: 0.4
    response_format: SEOAgentOutput
template:
  format: semantic-kernel
'''

# New lightweight agent to normalize / extract topic & length from a free-form user prompt.
PARAM_EXTRACTION_AGENT_YAML = '''
type: chat_completion_agent
name: BlogParamExtractionAgent
description: Extracts a concise blog topic and desired paragraph length from a free-form user prompt.
instructions: |
    You are given a user prompt that may describe a blog topic and optionally a desired number of paragraphs.
    Return ONLY a compact JSON object with keys:
        topic: concise title/topic (string, 3-80 chars)
        length: integer number of paragraphs (default 5 if absent or invalid; clamp between 1 and 20)
    Rules:
        - If no explicit length, use 5.
        - If length > 20 set to 20; if < 1 set to 1.
        - Do not add extra keys.
        - Output raw JSON (no code fences).
    User Prompt:
    {{$prompt}}
inputs:
    prompt:
        description: Free-form user prompt containing desired blog request.
        required: true
model:
    id: gpt-5-nano
    options:
        temperature: 0.1
template:
    format: semantic-kernel
'''

class BlogRequest(BaseModel):
    # Either provide structured topic (and optional length) OR a free-form prompt.
    topic: Optional[str] = None
    length: Optional[int] = 4
    prompt: Optional[str] = None

    def get_effective_prompt(self) -> str:
        return self.prompt or (self.topic or "")

class BlogContentResponse(BaseModel):
    content: str

class SEOAgentOutput(BaseModel):
    title: str
    meta_description: str
    slug: str
    h1: str
    h2s: List[str]
    revised_article: str
    improvements: List[str]
    seo_keywords: List[str]
    internal_links: List[str]
    external_links: List[str]
    readability_score: Optional[float]
    call_to_action: Optional[str]

class ParamExtraction(BaseModel):
    topic: str
    length: Optional[int] = 5

app = FastAPI()

class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        raw_body = await request.body()
        logger.debug(
            "REQUEST %s %s headers=%s body=%s",
            request.method,
            request.url.path,
            {k: v for k, v in request.headers.items() if k.lower() in ("content-type","content-length")},
            raw_body.decode(errors="replace")[:2000]
        )

        # Re-inject body so downstream can read it again
        async def receive():
            return {"type": "http.request", "body": raw_body, "more_body": False}
        request._receive = receive  # type: ignore

        response = await call_next(request)

        # Attempt to peek at response body if it's a JSONResponse
        try:
            if hasattr(response, "body_iterator"):
                # Don't consume streaming responses, just note type
                logger.debug("RESPONSE status=%s stream=%s", response.status_code, True)
            else:
                logger.debug("RESPONSE status=%s headers=%s", response.status_code, dict(response.headers))
        except Exception as e:
            logger.debug("RESPONSE logging error: %s", e)
        return response

app.add_middleware(RequestResponseLoggingMiddleware)

@ app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = (await request.body()).decode(errors="replace")
    logger.error("Validation error on %s %s: errors=%s raw_body=%s",
                 request.method, request.url.path, exc.errors(), body)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "raw_body": body}
    )

# Initialize the Azure OpenAI chat completion service for Semantic Kernel
# Use the same service for all agents
chat_completion_service = AzureChatCompletion(
    endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    deployment_name=AZURE_OPENAI_CHAT_DEPLOYMENT_NAME
)

@app.post("/echo")
async def echo_endpoint(payload: dict | None = Body(default=None)):
    return {"received": payload}

@app.post("/generate-blog")
async def generate_blog_endpoint(payload: BlogRequest | None = Body(default=None), request: Request = None):
    # Fallback: if body was a raw JSON string or plain text instead of an object
    
    if payload is None or (payload.topic is None and payload.prompt is None):
      logger.debug("No structured payload provided, attempting to parse raw body")
      raw = (await request.body()).decode(errors="replace") if request else ""
      raw_str = raw.strip()
      # If raw is JSON like "..." unwrap quotes
      if raw_str.startswith('"') and raw_str.endswith('"'):
        logger.debug("Raw body looks like JSON string, unwrapping quotes")
        raw_str = raw_str[1:-1]
      # If raw looks like JSON object try parse for prompt
      try:
        maybe_json = json.loads(raw)
        if isinstance(maybe_json, dict) and 'prompt' in maybe_json:
          raw_str = str(maybe_json['prompt'])
      except Exception:
        pass
      payload = BlogRequest(prompt=raw_str)
      logger.debug("Parsed blog request payload: %s", payload)

    # Should be default behavior
    else:
      logger.debug("Received structured BlogRequest payload: %s", payload)
      prompt = payload.get_effective_prompt()
      logger.debug("Using effective prompt: %s", prompt[:60] + '...' if len(prompt) > 60 else prompt)

    logger.info("START generate_blog input='%s'", (prompt[:60] + '...') if len(prompt) > 60 else prompt)
    try:
        result = await _generate_blog(payload)
        logger.info("SUCCESS generate_blog generated")
        return result
    except Exception as e:
        logger.exception("FAIL generate_blog error=%s", e)
        raise

async def _generate_blog(prompt: BlogRequest):
  import yaml
  
  logger.debug("## Start writing Blog article")
  az_responses_client = AzureResponsesAgent.create_client()
  logger.debug("Received prompt='%s'", prompt)
  try:
    if prompt.prompt is not None and prompt.topic is None:
      logger.debug("No topic is provided. Trying to extract topic and length from free form prompt.")
      # Step 1: Parameter extraction
      logger.info("### Running ParamExtractionAgent")
      free_form_prompt = prompt.get_effective_prompt()
      try:
          param_agent_declaration = yaml.safe_load(PARAM_EXTRACTION_AGENT_YAML)
          param_agent = AzureResponsesAgent(
              client=az_responses_client,
              name=param_agent_declaration["name"],
              instructions=param_agent_declaration["instructions"],
              ai_model_id=param_agent_declaration["model"]["id"],
              temperature=param_agent_declaration["model"]["options"].get("temperature", 0.2) if "gpt-5" not in str(param_agent_declaration["model"]["id"]).lower() else None, # temperature is not supported in the GPT-5 model family
          )
          
          param_response = await param_agent.get_response(
            thread=None,
            messages="Follow your instructions to extract parameters from this prompt.",
            prompt=free_form_prompt,
          )
          
          raw_params = param_response.message.content or "{}"
          logger.debug("Param extraction raw=%s", raw_params)
          # Attempt to parse the raw JSON response
          logger.debug("Attempting to parse param extraction JSON")
          try:
              parsed = json.loads(raw_params)
              extracted = ParamExtraction.model_validate(parsed)
              logger.debug("Param extraction successful: %s", extracted)
              # return extracted.model_dump_json()
          except Exception as e:
              logger.warning("Param extraction fallback using original inputs error=%s raw=%s", e, raw_params)
              extracted = ParamExtraction(topic=prompt.topic or free_form_prompt, length=prompt.length)
      except Exception:
          logger.exception("Param extraction agent failed; falling back to original inputs")
          extracted = ParamExtraction(topic=prompt.topic or free_form_prompt, length=prompt.length)
    else:
      logger.info("Using provided topic and length for blog generation: topic='%s' length=%s", prompt.topic, prompt.length)
      extracted = ParamExtraction(topic=prompt.topic, length=prompt.length)
      
    # Step 2: Blog generation
    logger.info("### Running BlogWriterAgent to generate first draft with topic='%s' length=%s", extracted.topic, extracted.length)
    blog_agent_declaration = yaml.safe_load(BLOG_POST_AGENT_YAML)
    blog_agent = AzureResponsesAgent(
        client=az_responses_client,
        name=blog_agent_declaration["name"],
        instructions=blog_agent_declaration["instructions"],
        ai_model_id=blog_agent_declaration["model"]["id"],
        temperature=blog_agent_declaration["model"]["options"].get("temperature", 0.2) if "gpt-5" not in str(blog_agent_declaration["model"]["id"]).lower() else None, # temperature is not supported in the GPT-5 model family
    )
    logger.debug("Trying to get a response from BlogWriterAgent for message=%s", extracted.model_dump_json())
    blog_agent_draft_response = await blog_agent.get_response(
        thread=None,
        messages="Follow your instructions to generate a blog article.",
        topic=extracted.topic,
        length=extracted.length
    )
    blog_article = blog_agent_draft_response.message.content
    logger.info("Blog article draft generated successfully: %s", blog_article[:60] + '...' if len(blog_article) > 60 else blog_article)

    # Step 3: SEO optimization
    logger.info("### Running SEOAgent to optimize blog article")
    execution_settings = AzureChatPromptExecutionSettings()
    execution_settings.response_format = SEOAgentOutput
    arguments = KernelArguments(settings=execution_settings)

    seo_agent_declaration = yaml.safe_load(SEO_AGENT_YAML)
    seo_agent = AzureResponsesAgent(
        client=az_responses_client,
        name=seo_agent_declaration["name"],
        instructions=seo_agent_declaration["instructions"],
        ai_model_id=seo_agent_declaration["model"]["id"],
        temperature=seo_agent_declaration["model"]["options"].get("temperature", 0.2) if "gpt-5" not in str(seo_agent_declaration["model"]["id"]).lower() else None, # temperature is not supported in the GPT-5 model family
        arguments=arguments, 
        text=AzureResponsesAgent.configure_response_format(SEOAgentOutput),
    )
    seo_agent_response = await seo_agent.get_response(
        thread=None,
        messages="Follow your instructions to optimize this blog article for SEO.",
        article=blog_article
    )
    seo_structured = seo_agent_response.message.content
    logger.debug("Raw SEO agent output: %s", seo_structured[:100] + '...' if len(seo_structured) > 100 else seo_structured)

    try:
        seo_result = SEOAgentOutput.model_validate(json.loads(seo_structured))
    except ValidationError as e:
        logger.error("SEOAgentOutput parsing error: %s raw=%s", e, seo_structured)
        raise HTTPException(
            status_code=500,
            detail=f"SEOAgentOutput parsing error: {e}\nRaw: {seo_structured}"
        )

    logger.info("SEO optimization completed successfully")

    # Feeding structured SEO output back into the BlogWriterAgent
    logger.info("Feeding structured SEO output back into the BlogWriterAgent")
    final_response = await blog_agent.get_response(
        thread=blog_agent_draft_response.thread,
        topic=extracted.topic,
        length=extracted.length,
        messages=seo_result.model_dump_json()
    )

    blog_content = BlogContentResponse(content=final_response.message.content)
    return blog_content
  except Exception as e:
      logger.exception("Unhandled error in generate_blog")
      raise HTTPException(status_code=500, detail=str(e))
    
if __name__ == "__main__":
  import asyncio
  topic = prompt("Enter blog topic: ")
  length = prompt("Enter blog length: ")
  user_prompt = BlogRequest(topic=topic, length=length)
  blog_article = asyncio.run(_generate_blog(prompt=user_prompt))
  print(blog_article)