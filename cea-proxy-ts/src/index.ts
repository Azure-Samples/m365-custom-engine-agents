// Import required packages
import {
  AuthConfiguration,
  authorizeJWT,
  loadAuthConfigFromEnv,
  Request,
} from "@microsoft/agents-hosting";
import express, { Response } from "express";

// This bot's adapter
import adapter from "./adapter";

// This bot's main dialog.
import { agentApp } from "./agent";

// Create authentication configuration
const authConfig: AuthConfiguration = loadAuthConfigFromEnv();

// Create express application.
const expressApp = express();
expressApp.use(express.json());
expressApp.use(authorizeJWT(authConfig));

const host = "0.0.0.0"; // Force IPv4
const port = Number(process.env.port || process.env.PORT) || 3978;

const server = expressApp.listen(port, host, () => {
  console.log(`\nAgent started, ${expressApp.name} listening to`, server.address());
});

// Listen for incoming requests.
expressApp.post("/api/messages", async (req: Request, res: Response) => {
  console.log("Received request:", req.body);
  await adapter.process(req, res, async (context) => {
    console.log("Processing request with agentApp");
    await agentApp.run(context);
  });
});
