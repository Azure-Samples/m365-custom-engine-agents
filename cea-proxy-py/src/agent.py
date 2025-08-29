from __future__ import annotations

from typing import Union
import os
import aiohttp
from microsoft.agents.hosting.core import ActivityHandler, MessageFactory, TurnContext
from microsoft.agents.activity import ChannelAccount

from pydantic import BaseModel, Field


class WeatherForecastAgentResponse(BaseModel):
    contentType: str = Field(pattern=r"^(Text|AdaptiveCard)$")
    content: Union[dict, str]


class CustomEngineAgent(ActivityHandler):
    def __init__(self):
        return super().__init__()
    
    async def on_members_added_activity(
        self, members_added: list[ChannelAccount], turn_context: TurnContext
    ):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity("Hello and welcome!")

    async def on_message_activity(self, turn_context: TurnContext):
        user_text = turn_context.activity.text or ""
        base_url = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
        endpoint = f"{base_url.rstrip('/')}/generate-blog"

        try:
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(endpoint, json={"prompt": user_text}) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        message = f"Request failed ({resp.status}). {err_text[:300]}"
                        activity = MessageFactory.text(message)
                        return await turn_context.send_activity(activity)

                    data = await resp.json(content_type=None)
                    content = data.get("content") if isinstance(data, dict) else None
                    if not content:
                        content = "No content returned from generator."

                    activity = MessageFactory.text(content)
                    return await turn_context.send_activity(activity)
        except Exception as e:
            activity = MessageFactory.text(f"Error contacting generator: {e}")
            return await turn_context.send_activity(activity)