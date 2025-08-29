"""
Copyright (c) Microsoft Corporation. All rights reserved.
Licensed under the MIT License.
"""

import os
from microsoft.agents.hosting.core import AuthTypes, AgentAuthConfiguration

from dotenv import load_dotenv

load_dotenv()

class Config:
    """Bot Configuration"""

    PORT = 3978
    APP_ID = os.environ.get("BOT_ID", "")
    APP_PASSWORD = os.environ.get("BOT_PASSWORD", "")
    APP_TYPE = os.environ.get("BOT_TYPE", "")
    APP_TENANTID = os.environ.get("BOT_TENANT_ID", "")
    # AZURE_OPENAI_API_KEY = os.environ["AZURE_OPENAI_API_KEY"] # Azure OpenAI API key
    # AZURE_OPENAI_MODEL_DEPLOYMENT_NAME = os.environ["AZURE_OPENAI_MODEL_DEPLOYMENT_NAME"] # Azure OpenAI model deployment name
    # AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"] # Azure OpenAI endpoint

class DefaultConfig(AgentAuthConfiguration):
    """Teams Agent Configuration"""

    def __init__(self) -> None:
        self.AUTH_TYPE = AuthTypes.client_secret
        self.TENANT_ID = "" or os.getenv(
            "TEAMS_APP_TENANT_ID"
        )
        self.CLIENT_ID = "" or os.getenv(
            "BOT_ID"
        )
        self.CLIENT_SECRET = "" or os.getenv(
            "BOT_PASSWORD"
        )
        self.CONNECTION_NAME = "" or os.getenv(
            "AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__GRAPH__SETTINGS__AZUREBOTOAUTHCONNECTIONNAME", "DefaultConnection"
        )
        self.AGENT_TYPE = os.getenv(
            "AGENT_TYPE", "TeamsHandler"
        )  # Default to TeamsHandler
        self.PORT = 3978