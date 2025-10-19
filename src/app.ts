import Fastify from "fastify";
import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import { config } from "./config/env";
import { userRoutes } from "./modules/users/users.routes";

export function buildApp() {
  const fastify = Fastify({
    logger: {
      level: config.nodeEnv === "development" ? "info" : "error",
    },
  });

  // Register plugins
  fastify.register(cors);
  fastify.register(helmet);

  // Health check
  fastify.get("/health", async () => {
    return { status: "ok", timestamp: new Date().toISOString() };
  });

  // Register routes
  fastify.register(userRoutes, { prefix: "/api" });

  return fastify;
}
