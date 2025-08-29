import { ActivityTypes } from "@microsoft/agents-activity";
import { AgentApplication, MemoryStorage, TurnContext } from "@microsoft/agents-hosting";
import { AzureOpenAI, OpenAI } from "openai";
import axios from "axios";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

// Define storage and application
const storage = new MemoryStorage();
export const agentApp = new AgentApplication({
  storage,
});

agentApp.conversationUpdate("membersAdded", async (context: TurnContext) => {
  console.log("New members added:", context.activity.membersAdded);
  // await context.sendActivity(`Hi there! I'm an agent to chat with you.`);
});

agentApp.activity(ActivityTypes.Typing, async (context: TurnContext) => {
  console.log("User is typing...");
  console.log(context.activity.toJsonString());
  // Optionally, you can send a typing activity back to the user
});

// Listen for ANY message to be received. MUST BE AFTER ANY OTHER MESSAGE HANDLERS
agentApp.activity(ActivityTypes.Message, async (context: TurnContext) => {
  console.log(`Received user message: ${context.activity.text}`);
  // Echo back users request
  // await context.sendActivity(`You said: ${context.activity.text}`);
  try {
    const result = await axios.post(
      `${BACKEND_URL}/generate-blog`,
      { prompt: context.activity.text },
      { headers: { "Content-Type": "application/json" } }
    );

    const data = result.data;
    let answer: string;

    if (typeof data === "string") {
      answer = data;
    } else if (data && typeof data === "object") {
      // Attempt common fields first; otherwise stringify the whole payload.
      console.log("Received data is of type: ", typeof data);
      if (typeof data.answer === "string" && data.answer) {
        answer = data.answer;
        console.log("Using field: data.answer");
      } else if (typeof data.result === "string" && data.result) {
        answer = data.result;
        console.log("Using field: data.result");
      } else if (typeof data.text === "string" && data.text) {
        answer = data.text;
        console.log("Using field: data.text");
      } else if (typeof data.content === "string" && data.content) {
        answer = data.content;
        console.log("Using field: data.content");
      } else {
        answer = JSON.stringify(data);
        console.log("Using fallback: JSON.stringify(data)");
      }
    } else {
      answer = String(data);
    }

    console.log("Generated answer:", answer.length > 100 ? answer.substring(0, 100) : answer);
    await context.sendActivity(answer);
  } catch (err) {
    console.log("Error calling backend:", err);
    await context.sendActivity("Sorry, I couldn't generate a response right now.");
  }
});
